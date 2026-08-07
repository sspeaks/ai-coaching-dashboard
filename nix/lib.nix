# Shared helpers for the services.aiCoaching module set.
#
# Kept intentionally small: these are option/type/assertion helpers reused
# across nix/*.nix files, not a general-purpose library.
{ lib }:
rec {
  # OCI containers always require an image name. For registry deployments it
  # must be a full digest reference. For imageFile deployments it must match
  # the name:tag stored in the local archive.
  mkImageOption =
    {
      description,
      default ? null,
      example ? null,
    }:
    lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      inherit default;
      example =
        if example != null then example else "registry.example.com/namespace/image@sha256:<64 hex chars>";
      description = ''
        ${description}

        Without `imageFile`, this must be a full digest-pinned registry
        reference (`name@sha256:` plus exactly 64 hexadecimal characters).
        With `imageFile`, it must instead match the name and tag embedded in
        that archive, as required by the NixOS OCI containers module.
      '';
    };

  # An `imageFile` option (path to a `docker load`-able tarball, e.g. produced
  # by `pkgs.dockerTools.buildLayeredImage`) for components that are built
  # locally rather than pulled from a registry.
  mkImageFileOption =
    description:
    lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        ${description}

        Locally generated image archive, for example a flake package produced
        by `pkgs.dockerTools.buildLayeredImage`. When set, `image` remains
        required and must match the archive's embedded name and tag.
      '';
    };

  isDigestPinned = image: image != null && builtins.match ".+@sha256:[0-9a-fA-F]{64}" image != null;

  # A remote image must be pinned. A local image archive uses a matching
  # name:tag and therefore intentionally does not use a registry digest.
  imageAssertions =
    {
      componentPath, # e.g. "services.aiCoaching.evidenceApi"
      enable,
      image,
      imageFile,
    }:
    [
      {
        assertion = !enable || image != null;
        message = ''
          ${componentPath}.enable is true but ${componentPath}.image is not
          set. Set either a registry digest, or a name:tag matching a local
          imageFile:
            ${componentPath}.image = "registry/namespace/name@sha256:<digest>";
          or:
            ${componentPath}.image = "ai-coaching/component:flake";
            ${componentPath}.imageFile = <docker-load archive>;
        '';
      }
      {
        assertion = !enable || imageFile != null || isDigestPinned image;
        message = ''
          ${componentPath}.image = "${toString image}" is a registry image
          without a valid 64-hex SHA-256 digest. Floating tags are not
          permitted unless imageFile supplies the matching local archive.
        '';
      }
    ];
}
