#!/usr/bin/with-contenv bashio
# ==============================================================================
# Remove socat service if MbusTCP is not enabled
# ==============================================================================
if [ "$(bashio::config 'MbusTCPenabled')" = "no" ]
then
    rm -r /etc/services.d/socat
fi
