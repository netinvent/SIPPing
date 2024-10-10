#!/usr/bin/env bash

endpoint=somehost.tld

rtt=$(/usr/bin/python3 /root/sipping3.py ${endpoint} -c 1 --rtt -q)

printf '# TYPE sip_rtt gauge\n' > /var/lib/node_exporter/textfile_collector/sip_rtt.prom
printf '# HELP sip_rtt roundtrip to SIP host in ms, 0.0 is bad roundtrip\n' >> /var/lib/node_exporter/textfile_collector/sip_rtt.prom
printf 'sip_rtt{sip_endpoint="'${endpoint}'"} '${rtt}'\n'  >> /var/lib/node_exporter/textfile_collector/sip_rtt.prom