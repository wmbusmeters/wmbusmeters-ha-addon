ARG BUILD_FROM
FROM ${BUILD_FROM} AS build

ENV LANG=C.UTF-8

RUN apk add --no-cache \
    alpine-sdk \
    pkgconf \
    gcc \
    linux-headers \
    libxml2-dev \
    cmake \
    libusb-dev \
    bash \
    samurai \
    libxslt-dev \
    jq

# Clone upstream repositories.
# Removed:
# ADD https://api.github.com/repos/wmbusmeters/wmbusmeters/git/refs/heads/master version.json
# This was only being used to invalidate Docker's cache and is now failing
# because GitHub returns HTTP 403 to the unauthenticated BuildKit request.
RUN git clone --depth 1 https://github.com/steve-m/librtlsdr.git && \
    git clone --depth 1 https://github.com/wmbusmeters/wmbusmeters.git && \
    git clone --depth 1 https://github.com/libxmq/xmq.git && \
    git clone --depth 1 https://github.com/wmbusmeters/rtl-wmbus.git && \
    git clone --depth 1 https://github.com/merbanan/rtl_433.git && \
    git clone --depth 1 https://github.com/ED6E0F17/rtl_reset.git

WORKDIR /librtlsdr
RUN cmake -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=MinSizeRel \
        -DCMAKE_INSTALL_PREFIX:PATH=/usr \
        -DDETACH_KERNEL_DRIVER=ON \
        -Wno-dev && \
    cmake --build build && \
    cmake --install build

WORKDIR /wmbusmeters
RUN ./configure && make

WORKDIR /xmq
RUN ./configure && make VERBOSE= && make install

#WORKDIR /wmbusmeters/drivers
#RUN make generate_ha_discovery

WORKDIR /rtl-wmbus
RUN make release && chmod 755 build/rtl_wmbus

WORKDIR /rtl_433
RUN cmake -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=MinSizeRel && \
    cmake --build build

WORKDIR /rtl_reset
RUN make


FROM ${BUILD_FROM} AS runtime

ENV QEMU_EXECVE=1
RUN apk add --no-cache pkgconf mosquitto-clients libstdc++ curl libusb libxml2 netcat-openbsd nginx

RUN apk add --no-cache \
    pkgconf \
    mosquitto-clients \
    libstdc++ \
    curl \
    libusb \
    libxml2 \
    netcat-openbsd \
    nginx \
    py3-pip \
    py3-cryptography \
    py3-flask \
    py3-requests \
    py3-waitress \
    py3-xmltodict

WORKDIR /wmbusmeters

COPY --from=build /librtlsdr/build/src/librtlsdr.so.* /usr/lib/
COPY --from=build /librtlsdr/rtl-sdr.rules /usr/lib/udev/rules.d/rtl-sdr.rules
COPY --from=build /librtlsdr/build/src/rtl_* /usr/bin/
COPY --from=build /wmbusmeters/build/wmbusmeters /wmbusmeters/wmbusmeters
COPY --from=build /rtl-wmbus/build/rtl_wmbus /usr/bin/rtl_wmbus
COPY --from=build /rtl_433/build/src/rtl_433 /usr/bin/rtl_433
COPY --from=build /rtl_reset/rtl_reset /usr/bin/rtl_reset

# first-telegram discovery hook, invoked by wmbusmeters' meter_shell config
COPY send_meter_discovery.sh /usr/bin/send_meter_discovery.sh
# the transform is used to convert telegram_with_details + driver to discovery json.
COPY to-ha-discovery.xslq /usr/bin/to-ha-discovery.xslq
RUN chmod a+x /usr/bin/send_meter_discovery.sh

COPY run.sh /
RUN chmod a+x /run.sh

COPY rootfs /

RUN chmod a+x \
    /etc/services.d/nginx/run \
    /etc/services.d/nginx/finish \
    /etc/services.d/flask/run \
    /etc/services.d/flask/finish \
    /etc/services.d/wmbusmeters/run \
    /etc/services.d/wmbusmeters/finish \
    /etc/cont-init.d/nginx.sh

ENTRYPOINT ["/init"]
