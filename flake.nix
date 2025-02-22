{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flakelight.url = "github:nix-community/flakelight";
  };
  
  outputs = { flakelight, ... }@inputs:
    flakelight ./. {
      inherit inputs;
      
      devShell = pkgs: {
        env.LD_LIBRARY_PATH = with pkgs; lib.makeLibraryPath [
          stdenv.cc.cc
        ];
        packages = with pkgs; [
          (python312.withPackages (ppkgs: with ppkgs; [
            pip
          ]))
        ];
      };
    };
}
