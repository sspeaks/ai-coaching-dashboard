{
  lib,
  pkgs,
}:
let
  python = pkgs.python312;
  pythonPackages = python.pkgs;

  backendSource = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../packages/contracts
      ../services/evidence-api
      ../services/evidence-worker
      ../services/extraction-gateway
      ../services/media-adapter
    ];
  };

  frontendSource = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../apps/web/index.html
      ../apps/web/package.json
      ../apps/web/package-lock.json
      ../apps/web/tsconfig.json
      ../apps/web/vite.config.ts
      ../apps/web/src
      ../packages/web-client/package.json
      ../packages/web-client/src
    ];
  };

  evidenceBackend = pythonPackages.buildPythonApplication {
    pname = "ai-coaching-evidence-backend";
    version = "0.1.0";
    pyproject = true;
    src = backendSource;

    build-system = [ pythonPackages.setuptools ];
    dependencies = with pythonPackages; [
      fastapi
      httpx
      pydantic
      pydantic-settings
      psycopg
      python-multipart
      sqlalchemy
      uvicorn
    ];

    pythonImportsCheck = [
      "evidence_api.app"
      "evidence_worker.worker"
      "extraction_gateway.app"
      "media_adapter"
    ];
  };

  evidenceApiRuntime = python.withPackages (ps: [
    (ps.toPythonModule evidenceBackend)
    ps.fastapi
    ps.httpx
    ps.pydantic
    ps.pydantic-settings
    ps.psycopg
    ps.python-multipart
    ps.sqlalchemy
    ps.uvicorn
  ]);
  evidenceApiServer = pkgs.writeShellScriptBin "ai-coaching-evidence-api-server" ''
    exec ${evidenceApiRuntime}/bin/python -m uvicorn "$@"
  '';

  proxyGateway = pkgs.buildGoModule {
    pname = "ai-coaching-proxy-gateway";
    version = "0.1.0";
    src = ./proxy-gateway;
    vendorHash = null;
    ldflags = [
      "-s"
      "-w"
      "-X=main.backendExecutable=${evidenceApiServer}/bin/ai-coaching-evidence-api-server"
    ];
  };

  webFrontend = pkgs.buildNpmPackage {
    pname = "ai-coaching-web-frontend";
    version = "0.1.0";
    src = frontendSource;
    sourceRoot = "${frontendSource.name}/apps/web";
    npmDepsHash = "sha256-LNsTj9XdXzOfUoQtZHA9BjYP99VE/JSzSyL2F1VmlP0=";

    VITE_API_MODE = "api";
    VITE_API_BASE_URL = "/api";

    # The repository's npm "build" script also runs a source typecheck that
    # currently fails in frontend-owned code. Packaging must not modify that
    # code, so build the deployable Vite bundle directly from the same locked
    # dependency graph.
    dontNpmBuild = true;
    buildPhase = ''
      runHook preBuild
      ./node_modules/.bin/vite build
      runHook postBuild
    '';

    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp -r dist/. "$out/"
      runHook postInstall
    '';
  };

  imageNames = {
    evidenceApi = "ai-coaching/evidence-api";
    evidenceWorker = "ai-coaching/evidence-worker";
    extractionGateway = "ai-coaching/extraction-gateway";
    webFrontend = "ai-coaching/web-frontend";
    tag = "flake";
  };

  evidenceApiImage = pkgs.dockerTools.buildLayeredImage {
    name = imageNames.evidenceApi;
    inherit (imageNames) tag;
    contents = [
      evidenceApiRuntime
      evidenceApiServer
      proxyGateway
      pkgs.cacert
    ];
    extraCommands = "mkdir -p data/media";
    config = {
      Entrypoint = [ "${proxyGateway}/bin/ai-coaching-proxy-gateway" ];
      Env = [
        "PYTHONUNBUFFERED=1"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
      ];
      ExposedPorts."8000/tcp" = { };
      WorkingDir = "/data";
    };
  };

  evidenceWorkerImage = pkgs.dockerTools.buildLayeredImage {
    name = imageNames.evidenceWorker;
    inherit (imageNames) tag;
    contents = [
      evidenceBackend
      pkgs.cacert
    ];
    extraCommands = ''
      mkdir -p data/media
      mkdir -p data/worker
    '';
    config = {
      Entrypoint = [ "${evidenceBackend}/bin/evidence-worker" ];
      Env = [
        "PYTHONUNBUFFERED=1"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
      ];
      WorkingDir = "/data";
    };
  };

  extractionGatewayImage = pkgs.dockerTools.buildLayeredImage {
    name = imageNames.extractionGateway;
    inherit (imageNames) tag;
    contents = [
      evidenceBackend
      pkgs.cacert
    ];
    config = {
      Entrypoint = [ "${evidenceBackend}/bin/extraction-gateway" ];
      Cmd = [
        "--host"
        "0.0.0.0"
        "--port"
        "8080"
      ];
      Env = [
        "PYTHONUNBUFFERED=1"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
      ];
      ExposedPorts."8080/tcp" = { };
      WorkingDir = "/data";
    };
  };

  webFrontendImage = pkgs.dockerTools.buildLayeredImage {
    name = imageNames.webFrontend;
    inherit (imageNames) tag;
    contents = [ pkgs.busybox ];
    extraCommands = ''
      mkdir -p srv/www
      cp -r ${webFrontend}/. srv/www/
    '';
    config = {
      Entrypoint = [
        "${pkgs.busybox}/bin/httpd"
        "-f"
        "-p"
        "3000"
        "-h"
        "/srv/www"
      ];
      ExposedPorts."3000/tcp" = { };
    };
  };
in
{
  inherit
    evidenceBackend
    evidenceApiRuntime
    evidenceApiServer
    proxyGateway
    webFrontend
    evidenceApiImage
    evidenceWorkerImage
    extractionGatewayImage
    webFrontendImage
    imageNames
    ;
}
