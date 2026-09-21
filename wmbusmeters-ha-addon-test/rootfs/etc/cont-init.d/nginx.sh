#!/usr/bin/with-contenv bashio
# ==============================================================================
# Configure NGINX for use with wmbusmeters ha-addon
# ==============================================================================
ingress_entry=$(bashio::addon.ingress_entry)
sed -i "s#%%ingress_entry%%#${ingress_entry}#g" /etc/nginx/nginx.conf
