# Caddy is the only public listener. It strips client-supplied identity and
# proxy-trust headers, obtains identity from oauth2-proxy, then injects a
# credential-backed hop header consumed by the API container's gateway.
{
  config,
  lib,
  ...
}:
let
  cfg = config.services.aiCoaching;
  inherit (cfg) oidc devAuth caddy;
  proxyAuthHeader = "X-AI-Coaching-Proxy-Auth";

  loopbackAddresses = [
    "127.0.0.1"
    "::1"
  ];

  untrustedHeaders = [
    "X-Auth-Request-User"
    "X-Auth-Request-Email"
    "X-Auth-Request-Groups"
    "X-Auth-Request-Preferred-Username"
    "X-Auth-Request-Access-Token"
    "X-Forwarded-User"
    "X-Forwarded-Email"
    "X-Forwarded-Groups"
    "X-Forwarded-Preferred-Username"
    "X-Forwarded-Access-Token"
    "X-Forwarded-For"
    "X-Forwarded-Host"
    "X-Forwarded-Proto"
    "X-Forwarded-Port"
    "X-Forwarded-Server"
    "X-Real-IP"
    "X-Original-URL"
    "X-Original-URI"
    "X-Remote-User"
    "X-Remote-Email"
    "X-Remote-Groups"
    "Remote-User"
    "Remote-Groups"
    "Forwarded"
    "Proxy-Authorization"
    proxyAuthHeader
  ];

  stripUntrustedHeaders = lib.concatMapStringsSep "\n" (
    header: "request_header -${header}"
  ) untrustedHeaders;

  forwardAuth = lib.optionalString oidc.enable ''
    forward_auth 127.0.0.1:${toString oidc.port} {
      uri /oauth2/auth
      copy_headers X-Auth-Request-User X-Auth-Request-Email X-Auth-Request-Groups X-Auth-Request-Preferred-Username
    }
  '';

  apiUpstream = "127.0.0.1:${toString cfg.evidenceApi.hostPort}";
  apiReverseProxy = ''
    reverse_proxy ${apiUpstream} {
      header_up ${proxyAuthHeader} {env.AI_COACHING_PROXY_AUTH_SECRET}
    }
  '';

  frontendHandler =
    if !cfg.webFrontend.enable then
      ''
        handle {
          ${forwardAuth}
          respond "frontend disabled" 404
        }
      ''
    else if cfg.webFrontend.mode == "staticRoot" then
      ''
        handle {
          ${forwardAuth}
          root * ${cfg.webFrontend.staticRoot}
          try_files {path} /index.html
          file_server
        }
      ''
    else
      ''
        handle {
          ${forwardAuth}
          reverse_proxy 127.0.0.1:${toString cfg.webFrontend.hostPort}
        }
      '';
in
{
  options.services.aiCoaching = {
    oidc = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Authenticate browser/API requests with an explicit OIDC provider through oauth2-proxy.";
      };

      issuerUrl = lib.mkOption {
        type = lib.types.str;
        default = "";
        example = "https://login.example.org/realms/coaching";
        description = "OIDC discovery issuer URL. Required in production.";
      };

      clientID = lib.mkOption {
        type = lib.types.str;
        default = "";
        description = "OIDC client ID. Required in production.";
      };

      clientSecretFile = lib.mkOption {
        type = lib.types.path;
        default = "${cfg.secretsDir}/oidc-client-secret";
        description = "File containing the OIDC client secret; never copied to the Nix store.";
      };

      cookieSecretFile = lib.mkOption {
        type = lib.types.path;
        default = "${cfg.secretsDir}/oauth2-proxy-cookie-secret";
        description = "File containing a base64-encoded 32-byte oauth2-proxy cookie secret.";
      };

      scopes = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [
          "openid"
          "email"
          "profile"
        ];
        description = "Explicit OIDC scopes requested by oauth2-proxy.";
      };

      emailClaim = lib.mkOption {
        type = lib.types.str;
        default = "email";
        description = "Verified OIDC claim copied to X-Auth-Request-Email for FastAPI.";
      };

      groupsClaim = lib.mkOption {
        type = lib.types.str;
        default = "groups";
        description = "Verified OIDC claim copied to X-Auth-Request-Groups for FastAPI authorization.";
      };

      adminGroups = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ "evidence-admins" ];
        description = "OIDC group names mapped to the backend admin role.";
      };

      editorGroups = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ "evidence-editors" ];
        description = "OIDC group names mapped to the backend editor role.";
      };

      emailDomains = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        example = [ "example.org" ];
        description = "Allowed authenticated email domains. Empty denies every login.";
      };

      port = lib.mkOption {
        type = lib.types.port;
        default = 4180;
        description = "Loopback port for oauth2-proxy.";
      };

      redirectURL = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "OIDC callback URL; defaults to https://<domain>/oauth2/callback.";
      };
    };

    devAuth.enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Use FastAPI development auth. Allowed only on a loopback Caddy listener.";
    };

    proxyAuth.environmentFile = lib.mkOption {
      type = lib.types.path;
      default = "${cfg.secretsDir}/proxy-auth.env";
      description = ''
        Root-readable environment file shared only by Caddy and the evidence
        API gateway. It must define AI_COACHING_PROXY_AUTH_SECRET as a random
        value of at least 32 characters. Caddy injects it after stripping the
        client header; the gateway rejects direct peer-container requests
        that cannot prove possession of the credential.
      '';
    };

    caddy = {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Manage Caddy as the sole public edge.";
      };

      acmeEmail = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
        description = "ACME contact email.";
      };

      extraConfig = lib.mkOption {
        type = lib.types.lines;
        default = "";
        description = "Additional trusted operator Caddy directives appended after module routes.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = oidc.enable != devAuth.enable;
        message = "Exactly one of services.aiCoaching.oidc.enable and devAuth.enable must be true.";
      }
      {
        assertion = !devAuth.enable || builtins.elem cfg.bindAddress loopbackAddresses;
        message = "Development auth is permitted only when Caddy bindAddress is loopback.";
      }
      {
        assertion = !oidc.enable || (oidc.issuerUrl != "" && oidc.clientID != "");
        message = "oidc.issuerUrl and oidc.clientID are required when OIDC is enabled.";
      }
      {
        assertion = !oidc.enable || oidc.emailDomains != [ ];
        message = "oidc.emailDomains must explicitly allow at least one domain.";
      }
      {
        assertion = !oidc.enable || builtins.elem "openid" oidc.scopes;
        message = "oidc.scopes must include openid.";
      }
      {
        assertion = !oidc.enable || oidc.emailClaim != "";
        message = "oidc.emailClaim must name the verified claim FastAPI will trust.";
      }
      {
        assertion = !oidc.enable || oidc.groupsClaim != "";
        message = "oidc.groupsClaim must name the verified claim FastAPI will use for roles.";
      }
      {
        assertion = lib.all (group: group != "" && builtins.match ".*,.*" group == null) (
          oidc.adminGroups ++ oidc.editorGroups
        );
        message = "oidc.adminGroups and oidc.editorGroups must contain non-empty group names without commas.";
      }
    ];

    services.oauth2-proxy = lib.mkIf oidc.enable {
      enable = true;
      provider = "oidc";
      oidcIssuerUrl = oidc.issuerUrl;
      inherit (oidc) clientID clientSecretFile;
      cookie = {
        secretFile = oidc.cookieSecretFile;
        secure = true;
        httpOnly = true;
      };
      email.domains = oidc.emailDomains;
      scope = lib.concatStringsSep " " oidc.scopes;
      redirectURL =
        if oidc.redirectURL != null then oidc.redirectURL else "https://${cfg.domain}/oauth2/callback";
      httpAddress = "http://127.0.0.1:${toString oidc.port}";
      upstream = [ "static://202" ];
      reverseProxy = true;
      trustedProxyIP = [
        "127.0.0.1/32"
        "::1/128"
      ];
      setXauthrequest = true;
      passBasicAuth = false;
      passAccessToken = false;
      extraConfig = {
        pass-user-headers = true;
        skip-auth-strip-headers = true;
        oidc-email-claim = oidc.emailClaim;
        oidc-groups-claim = oidc.groupsClaim;
        insecure-oidc-allow-unverified-email = false;
      };
    };

    systemd.services.oauth2-proxy = lib.mkIf oidc.enable {
      after = [ "network-online.target" ];
      serviceConfig = {
        Restart = lib.mkForce "on-failure";
        RestartSec = 5;
      };
    };

    systemd.services.caddy = lib.mkIf (caddy.enable && cfg.evidenceApi.enable) {
      serviceConfig.EnvironmentFile = cfg.proxyAuth.environmentFile;
    };

    services.caddy = lib.mkIf caddy.enable {
      enable = true;
      email = caddy.acmeEmail;
      virtualHosts.${cfg.domain} = {
        listenAddresses = lib.optionals (cfg.bindAddress != "0.0.0.0") [ cfg.bindAddress ];
        extraConfig = ''
          encode gzip zstd

          # Drop untrusted identity, group, proxy-chain, and hop credentials
          # before any route can authenticate or reach an upstream.
          ${stripUntrustedHeaders}

          ${lib.optionalString oidc.enable ''
            handle /oauth2/* {
              reverse_proxy 127.0.0.1:${toString oidc.port}
            }
          ''}

          ${lib.optionalString cfg.evidenceApi.enable ''
            # Speakr webhooks authenticate with the backend's signed webhook
            # contract, not an interactive browser OIDC session. The path is
            # preserved because the FastAPI contract is rooted at /api.
            handle /api/webhooks/speakr {
              ${apiReverseProxy}
            }

            redir /api /api/ 308
            handle /api/* {
              ${forwardAuth}
              ${apiReverseProxy}
            }
          ''}

          ${frontendHandler}

          ${caddy.extraConfig}
        '';
      };
    };

    networking.firewall.allowedTCPPorts = lib.optionals caddy.enable [
      80
      443
    ];
  };
}
