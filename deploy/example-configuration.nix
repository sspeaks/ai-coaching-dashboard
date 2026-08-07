# Import this module from a host flake whose `specialArgs.inputs` contains an
# input named `ai-coaching-dashboard`. It uses only artifacts built from that
# pinned flake input; there are no placeholder registry digests.
{
  inputs,
  pkgs,
  ...
}:
let
  artifacts = inputs.ai-coaching-dashboard.packages.${pkgs.stdenv.hostPlatform.system};
in
{
  services.aiCoaching = {
    enable = true;
    domain = "coaching.example.org";
    bindAddress = "0.0.0.0";
    dataDir = "/var/lib/ai-coaching";
    secretsDir = "/var/lib/ai-coaching/secrets";

    network = {
      name = "ai-coaching";
      subnet = "10.89.1.0/24";
    };

    oidc = {
      enable = true;
      issuerUrl = "https://login.example.org/realms/coaching";
      clientID = "ai-coaching-dashboard";
      scopes = [
        "openid"
        "email"
        "profile"
      ];
      emailClaim = "email";
      groupsClaim = "groups";
      emailDomains = [ "example.org" ];
      adminGroups = [ "evidence-admins" ];
      editorGroups = [ "evidence-editors" ];
    };
    devAuth.enable = false;

    caddy = {
      enable = true;
      acmeEmail = "admin@example.org";
    };

    postgresql = {
      enable = true;
      databaseName = "evidence";
      username = "evidence";
    };

    # Fixed and read-only in the module:
    # learnedmachine/speakr@sha256:425a39e101ee69abe67e86ad53fec0b4ef7b13caed2ab30f388022beca8fdaf6
    speakr.enable = true;

    evidenceApi = {
      enable = true;
      image = "ai-coaching/evidence-api:flake";
      imageFile = artifacts.evidence-api-image;
    };

    evidenceWorker = {
      enable = true;
      image = "ai-coaching/evidence-worker:flake";
      imageFile = artifacts.evidence-worker-image;
    };

    webFrontend = {
      enable = true;
      mode = "container";
      image = "ai-coaching/web-frontend:flake";
      imageFile = artifacts.web-frontend-image;
    };

    backup = {
      enable = true;
      onCalendar = "*-*-* 03:30:00";
      retainCount = 14;
    };
  };
}
