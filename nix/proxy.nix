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

  # Scheme used when sending an unauthenticated browser to the sign-in flow.
  # Under external TLS termination Caddy itself listens on plain HTTP, so
  # {scheme} would resolve to "http" and oauth2-proxy would build an
  # http:// redirect URI that no longer matches the registered OIDC callback.
  redirectScheme = if caddy.externalTls.enable then "https" else "{scheme}";
  stripTrailingSlash =
    value:
    let
      match = builtins.match "(.+)/" value;
    in
    if match == null then value else builtins.head match;
  oidcEndSessionURL =
    if oidc.singleLogout.endSessionURL != null then
      oidc.singleLogout.endSessionURL
    else
      "${stripTrailingSlash oidc.issuerUrl}/end-session/";
  oidcBackendLogoutURL =
    "${oidcEndSessionURL}?id_token_hint={id_token}"
    + lib.optionalString (
      oidc.singleLogout.postLogoutRedirectURL != null
    ) "&post_logout_redirect_uri=${oidc.singleLogout.postLogoutRedirectURL}";

  forwardAuth = lib.optionalString oidc.enable ''
    forward_auth 127.0.0.1:${toString oidc.port} {
      uri /oauth2/auth
      ${lib.optionalString caddy.externalTls.enable ''
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-Host {host}
        header_up X-Forwarded-Port 443
      ''}
      copy_headers X-Auth-Request-User X-Auth-Request-Email X-Auth-Request-Groups X-Auth-Request-Preferred-Username

      # Without this, Caddy passes oauth2-proxy's 401 straight back to the
      # browser and the user can never reach the identity provider.
      @error status 401
      handle_response @error {
        redir * /oauth2/start?rd=${redirectScheme}://{host}{uri}
      }
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
          # route enforces written directive order so forward_auth runs before
          # try_files. Without route, Caddy's standard directive ordering
          # executes try_files (a rewrite) first, rewriting "/" to "/index.html"
          # before forward_auth captures {uri} for the post-login redirect —
          # causing oauth2-proxy to redirect users to /index.html after login
          # instead of their original path. See issue #28.
          route {
            ${forwardAuth}
            root * ${cfg.webFrontend.staticRoot}
            try_files {path} /index.html
            file_server
          }
        }
      ''
    else
      ''
        handle {
          ${forwardAuth}
          reverse_proxy 127.0.0.1:${toString cfg.webFrontend.hostPort}
        }
      '';
  caddySite =
    if caddy.externalTls.enable then
      "http://${cfg.domain}:${toString caddy.externalTls.httpPort}"
    else
      cfg.domain;
  externalTlsOauth2ProxyHeaders = lib.optionalString caddy.externalTls.enable ''
    header_up X-Forwarded-Proto https
    header_up X-Forwarded-Host {host}
    header_up X-Forwarded-Port 443
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

      allowUnverifiedEmail = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = ''
          Accept an id_token whose email_verified claim is not true.

          authentik 2025.10 and later deliberately emit email_verified = false
          because authentik has no email-verification feature and will not
          assert something it cannot prove, so every authentik login fails the
          default check with "email in id_token isn't verified".

          The evidence API uses this email as the principal subject, which is
          what ledger entries are attributed to. Only enable this when the
          identity provider is the sole authority for that address — users are
          admin-provisioned and cannot self-register or change their own email.
          If users can set their own address, enabling this lets one user be
          attributed as another.
        '';
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

      singleLogout = {
        enable = lib.mkOption {
          type = lib.types.bool;
          default = true;
          description = ''
            End the upstream OIDC SSO session when the dashboard sign-out link
            is used. By default the request omits postLogoutRedirectURL, so
            providers such as Authentik end the SSO session without requiring
            a pre-registered redirect URI. Set postLogoutRedirectURL only after
            registering it with the provider to return users to /signed-out.
          '';
        };

        endSessionURL = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          description = ''
            OIDC RP-initiated logout endpoint. Null derives Authentik's
            default endpoint from issuerUrl by appending /end-session/.
          '';
        };

        postLogoutRedirectURL = lib.mkOption {
          type = lib.types.nullOr lib.types.str;
          default = null;
          example = "https://streams.example.org/signed-out";
          description = ''
            Registered final browser destination after OIDC logout. When null,
            the logout request is sent without post_logout_redirect_uri and the
            identity provider chooses its own signed-out destination.
          '';
        };
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

      externalTls = {
        enable = lib.mkOption {
          type = lib.types.bool;
          default = false;
          description = ''
            Serve plain HTTP on `httpPort` because TLS is terminated by an
            operator-managed reverse proxy in front of this host. This keeps
            oauth2-proxy cookies secure and its redirects HTTPS-aware while
            disabling this host's ACME/automatic HTTPS for the dashboard vhost.
          '';
        };

        httpPort = lib.mkOption {
          type = lib.types.port;
          default = 8080;
          description = "Plain HTTP port Caddy listens on when external TLS termination is enabled.";
        };
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
      {
        assertion = !caddy.externalTls.enable || oidc.enable;
        message = "caddy.externalTls.enable is supported only with OIDC enabled so secure cookie and redirect behavior remains explicit.";
      }
      {
        assertion = !caddy.externalTls.enable || caddy.acmeEmail == null;
        message = "caddy.acmeEmail must be null when caddy.externalTls.enable is true because this host does not manage ACME for the dashboard vhost.";
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
        insecure-oidc-allow-unverified-email = oidc.allowUnverifiedEmail;
      }
      // lib.optionalAttrs oidc.singleLogout.enable {
        backend-logout-url = oidcBackendLogoutURL;
        whitelist-domain = cfg.domain;
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
      virtualHosts.${caddySite} = {
        listenAddresses = lib.optionals (cfg.bindAddress != "0.0.0.0") [ cfg.bindAddress ];
        extraConfig = ''
          encode gzip zstd

          # Drop untrusted identity, group, proxy-chain, and hop credentials
          # before any route can authenticate or reach an upstream.
          ${stripUntrustedHeaders}

          ${lib.optionalString oidc.enable ''
            handle /signed-out {
              respond "Signed out. Your Quartet coaching session has ended. If Authentik returned you here, its sign-in session has also ended." 200
            }

            handle /oauth2/* {
              reverse_proxy 127.0.0.1:${toString oidc.port} {
                ${externalTlsOauth2ProxyHeaders}
              }
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

    networking.firewall.allowedTCPPorts =
      lib.optionals (caddy.enable && !caddy.externalTls.enable) [
        80
        443
      ]
      ++ lib.optionals (caddy.enable && caddy.externalTls.enable) [
        caddy.externalTls.httpPort
      ];
  };
}
