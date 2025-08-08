# This folder is to develop xApp RAN Control

## For source codes, find them here https://openaicellular.github.io/oaic/OAIC-2024-Workshop-oai-flexric-documentation.html

## In this folder, source codes are already cloned.


## RAN & UE - at commit `oaic_workshop_2024_v1` with E2 interface
```bash
cd oai-oaic_workshop_2024_v1/cmake_targets/
./build_oai -I -w SIMU --gNB --nrUE --build-e2 --ninja
```


## FlexRIC - at commit `beabdd072`
```bash
cd flexric-beabdd072/
mkdir build
cd build
cmake ../
make -j`nproc`
sudo make install
```

