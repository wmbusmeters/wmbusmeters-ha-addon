#!/usr/bin/with-contenv bashio


MbusTCPtty=$(bashio::config 'MbusTCPtty')
MbusTCPttyBaud=$(bashio::config 'MbusTCPttyBaud')
MbusTCPhost=$(bashio::config 'MbusTCPhost')
MbusTCPhostPort=$(bashio::config 'MbusTCPhostPort')

bashio::log.info "(socat) Testing is MbusTCP accessible ..."
if nc -w 3 -z $MbusTCPhost $MbusTCPhostPort > /dev/null
then
    bashio::log.info "(socat) $MbusTCPhost:$MbusTCPhostPort MbusTCP is accessible on $(dig +short $MbusTCPhost) IP"
    bashio::log.info "(socat) Running socat pty,group-late=tty,link=$MbusTCPtty,mode=660,rawer,echo=0,b$MbusTCPttyBaud,waitslave,ignoreeof tcp:$MbusTCPhost:$MbusTCPhostPort"
    if pgrep socat > /dev/null; then
        pkill socat
    fi
    socat pty,group-late=tty,link=$MbusTCPtty,mode=660,rawer,echo=0,b$MbusTCPttyBaud,waitslave,ignoreeof tcp:$MbusTCPhost:$MbusTCPhostPort
else
    bashio::log.info "(socat) $MbusTCPhost:$MbusTCPhostPort MbusTCP is not accessible on $(dig +short $MbusTCPhost) IP"
    sleep 1
fi        

#socat pty,group-late=tty,link=/root/ttyMBUS0,mode=660,rawer,echo=0,b2400,waitslave,ignoreeof tcp:192.168.3.9:2003
