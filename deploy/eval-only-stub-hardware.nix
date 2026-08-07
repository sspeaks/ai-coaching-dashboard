# Minimal fileSystems/bootloader stub so `nixosSystem { ... }.config.system.build.toplevel`
# can be evaluated/built by `flake.nix`'s `checks` output without a real
# target machine. Not meant to boot anything -- purely to satisfy NixOS's
# "you must have a root filesystem and a bootloader" assertions during
# static evaluation of the `services.aiCoaching` module.
{
  system.stateVersion = "26.05";
  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "ext4";
  };
  boot.loader.grub.enable = false;
  boot.loader.generic-extlinux-compatible.enable = true;
}
