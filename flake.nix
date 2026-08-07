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
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              nixfmt
              statix
              deadnix
              skopeo
            ];
          };
        }
      );
    };
}
