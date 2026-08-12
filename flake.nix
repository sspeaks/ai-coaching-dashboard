{
  description = "Reproducible application packages, OCI images, and NixOS deployment for the AI coaching dashboard.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forEachSystem = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: import nixpkgs { inherit system; };
      artifactsFor =
        system:
        import ./nix/packages.nix {
          inherit (nixpkgs) lib;
          pkgs = pkgsFor system;
        };
    in
    {
      nixosModules.aiCoaching = import ./nix/module.nix;
      nixosModules.default = self.nixosModules.aiCoaching;

      packages = forEachSystem (
        system:
        let
          artifacts = artifactsFor system;
        in
        {
          evidence-backend = artifacts.evidenceBackend;
          web-frontend = artifacts.webFrontend;
          evidence-api-image = artifacts.evidenceApiImage;
          evidence-worker-image = artifacts.evidenceWorkerImage;
          extraction-gateway-image = artifacts.extractionGatewayImage;
          web-frontend-image = artifacts.webFrontendImage;
          default = artifacts.webFrontend;
        }
      );

      checks = forEachSystem (
        system:
        import ./nix/checks.nix {
          inherit
            self
            nixpkgs
            system
            ;
          pkgs = pkgsFor system;
          artifacts = artifactsFor system;
        }
      );

      devShells = forEachSystem (
        system:
        let
          pkgs = pkgsFor system;
          uxFonts = with pkgs; [
            dejavu_fonts
            liberation_ttf
            noto-fonts
            noto-fonts-cjk-sans
            noto-fonts-color-emoji
          ];
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              nodejs_24
              nixfmt
              statix
              deadnix
              skopeo
              fontconfig
              liberation_ttf
              noto-fonts
              noto-fonts-cjk-sans
              noto-fonts-color-emoji
              playwright-driver.browsers
            ];
            FONTCONFIG_FILE = pkgs.makeFontsConf { fontDirectories = uxFonts; };
            PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";
            PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
          };
        }
      );
    };
}
