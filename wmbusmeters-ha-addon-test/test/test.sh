#!/bin/bash

if [ ! -f "$1" ] || [ ! -f "$2" ] || [ -z "$3" ]
then
   echo "Usage: test.sh [telegram] [driver] [output]"
   exit 0
fi

TELEGRAM=$(<$1)
DRIVER=$(<$2)

../send_meter_discovery.sh "$TELEGRAM" "$DRIVER" "$3"
