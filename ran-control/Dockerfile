# Dockerfile for gNB and FlexRIC with RAN control
# ---- Stage 1: Build Stage ----
FROM ubuntu:22.04 AS builder

# Avoid interactive frontend
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes && \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes \
        build-essential \
        git \
        gcc-12 \
        g++-12 \
        cpp-12 \
        libsctp-dev \
        cmake-curses-gui \
        libpcre2-dev \
        automake \
        bison \
        python-dev-is-python3 \
        make && \
    apt-get clean

# # Set GCC version to gcc-12
RUN update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 100 \
    --slave /usr/bin/g++ g++ /usr/bin/g++-12 \
    --slave /usr/bin/gcov gcov /usr/bin/gcov-12 && \
    update-alternatives --set gcc /usr/bin/gcc-12

# Build and install SWIG
WORKDIR /opt
RUN git clone --branch release-4.1 --single-branch https://github.com/swig/swig.git && \
    cd swig && \
    ./autogen.sh && \
    ./configure --prefix=/usr/ && \
    make -j$(nproc) && \
    make install

# Clone and build OpenAirInterface
WORKDIR /opt
RUN git clone https://gitlab.eurecom.fr/oai/openairinterface5g oai
WORKDIR /opt/oai
RUN git checkout oaic_workshop_2024_v1
WORKDIR /opt/oai/cmake_targets
RUN ./build_oai -I -w SIMU --gNB --nrUE --build-e2 --ninja

WORKDIR /opt
RUN git clone https://gitlab.eurecom.fr/mosaic5g/flexric flexric && \
    cd flexric && \
    git checkout beabdd07 && \
    mkdir build && cd build && \
    cmake .. && make -j8 && \
    make install

# ---- Stage 2: Runtime Stage ----
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get upgrade --yes && \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes \
        software-properties-common \
        procps \
        libsctp1 \
        libboost-chrono1.74.0 \
        libboost-date-time1.74.0 \
        libboost-filesystem1.74.0 \
        libboost-regex1.74.0 \
        libboost-serialization1.74.0 \
        libboost-thread1.74.0 \
        libboost-system1.74.0 \
        libboost-program-options1.74.0 \
        tzdata \
        libblas3 \
        libconfig9 \
        openssl \
        net-tools \
        iperf \
        iperf3 \
        iproute2 \
        iputils-ping \
        gdb \
        python3 \
        python3-six \
        python3-requests \
        libusb-1.0-0 \
        libyaml-cpp-dev && \
    apt-get clean -y && \
    rm -rf /var/lib/apt/lists/*



# Copy built binaries from builder
COPY --from=builder /opt/oai /opt/oai
COPY --from=builder /opt/flexric /opt/flexric
COPY --from=builder /usr/bin/swig /usr/bin/swig
COPY --from=builder /usr/lib*/libswig* /usr/lib/
COPY --from=builder /usr/local/lib/flexric /usr/local/lib/flexric

# Set default working directory
WORKDIR /opt/oai/cmake_targets/ran_build/build

# Default command (can be overridden)
# CMD ["bash"]
# command to run xApps
# /opt/flexric/build/examples/xApp/c/monitor/xapp_kpm_moni
# /opt/flexric/build/examples/xApp/c/kpm_rc/xapp_kpm_rc