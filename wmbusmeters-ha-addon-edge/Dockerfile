ARG BUILD_FROM
FROM $BUILD_FROM AS build

ENV LANG C.UTF-8

RUN apk add --no-cache alpine-sdk gcc linux-headers libxml2-dev cmake libusb-dev bash samurai libxslt-dev pkgconf jq

ADD https://api.github.com/repos/wmbusmeters/wmbusmeters/git/refs/heads/master version.json
RUN git clone https://github.com/steve-m/librtlsdr.git && \
    git clone https://github.com/wmbusmeters/wmbusmeters.git && \
    git clone https://github.com/libxmq/xmq.git && \
    git clone https://github.com/weetmuts/rtl-wmbus.git && \
    git clone https://github.com/merbanan/rtl_433.git && \
    git clone https://github.com/ED6E0F17/rtl_reset.git

WORKDIR /librtlsdr
RUN cmake -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=MinSizeRel \
        -DCMAKE_INSTALL_PREFIX:PATH=/usr \
        -DDETACH_KERNEL_DRIVER=ON \
        -Wno-dev && \
    cmake --build build && \
    cmake --install build

WORKDIR /wmbusmeters
RUN make

#WORKDIR /xmq
#RUN ./configure && make VERBOSE= && make install

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

FROM $BUILD_FROM AS scratch
ENV QEMU_EXECVE=1
RUN apk add --no-cache mosquitto-clients libstdc++ curl libusb libxml2 netcat-openbsd nginx

# Install Flask
RUN apk add --update py3-pip py3-cryptography
RUN pip install flask requests waitress xmltodict

WORKDIR /wmbusmeters
COPY --from=build /librtlsdr/build/src/librtlsdr.so.* /usr/lib/
COPY --from=build /librtlsdr/rtl-sdr.rules /usr/lib/udev/rules.d/rtl-sdr.rules
COPY --from=build /librtlsdr/build/src/rtl_* /usr/bin/
COPY --from=build /wmbusmeters/build/wmbusmeters /wmbusmeters/wmbusmeters
#COPY --from=build /wmbusmeters/drivers/build/ha_mqtt_discovery/ /ha_mqtt_discovery/
COPY --from=build /rtl-wmbus/build/rtl_wmbus /usr/bin/rtl_wmbus
COPY --from=build /rtl_433/build/src/rtl_433 /usr/bin/rtl_433
COPY --from=build /rtl_reset/rtl_reset /usr/bin/rtl_reset

ADD mqtt_discovery/ /mqtt_discovery/
COPY mqtt_discovery.sh /
RUN chmod a+x /mqtt_discovery.sh

COPY run.sh /
RUN chmod a+x /run.sh

COPY rootfs /
RUN chmod a+x /etc/services.d/nginx/run
RUN chmod a+x /etc/services.d/nginx/finish
RUN chmod a+x /etc/services.d/flask/run
RUN chmod a+x /etc/services.d/flask/finish
RUN chmod a+x /etc/cont-init.d/nginx.sh

CMD ["/run.sh"]
