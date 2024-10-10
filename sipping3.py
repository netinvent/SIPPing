#!/usr/bin/python3
"""

======This version modified for Python3========

SIP Ping - A diagnostic utility for critical VoIP monitoring
Created by Daniel Thompson
Version 2.0

==========================================================================

Software License:
Do whatever you want with this code. There are no restrictions.

Not-license:
I'd like to hear back from you if you do something interesting with this.

==========================================================================

SIP Ping is a tool for monitoring a SIP gateway (PBX, SBC, phone) for deep
dive diagnostics. Most tools for VoIP monitoring are based on meeting SLA
figures and providing general "network availability" statistics. SIP Ping
is for granular troubleshooting.

See http://gekk.info/sipping for more information and suggested usage.
Commandline flags and defaults are available by running "python sipping.py -h"

"""

import sys
import random
import re
import os
import socket
import argparse
from datetime import datetime
import time

# handler for ctrl+c / SIGINT
# last action before quitting is to write a \n to the end of the output file
import signal


def signal_handler(sig, frame):
    print("\nCtrl+C ({}:{})- exiting.".format(sig, frame))
    if v_logpath != "*":
        with open(v_logpath, "a", encoding="utf-8") as _f_log:
            _f_log.write("\n")
    printstats()
    sys.exit(0)


def printstats():
    # loss stats
    print(("\t[Recd: {recd} | Lost: {lost}]".format(recd=v_recd, lost=v_lost)), end=" ")

    if v_longest_run > 0:
        print(("\t[loss stats:"), end=" ")
        print(("longest run: " + str(v_longest_run)), end=" ")
    if v_last_run_loss > 0:
        print((" length of last run: " + str(v_last_run_loss)), end=" ")
    if v_current_run_loss > 0:
        print((" length of current run: " + str(v_current_run_loss)), end=" ")
    print("]")

    # min max avg
    v_total = 0
    for i in l_history:
        v_total = v_total + i
    if v_total > 0:
        v_avg = v_total / len(l_history)
    else:
        v_avg = 0
        print(
            (
                "\t[min/max/avg {min}/{max}/{avg}]".format(
                    min=v_min, max=v_max, avg=v_avg
                )
            )
        )


# create and execute command line parser

parser = argparse.ArgumentParser(
    description="Send SIP OPTIONS messages to a host and measure response time. Results are logged continuously to CSV."
)
parser.add_argument("host", help="Target SIP device to ping")
parser.add_argument(
    "-I",
    metavar="interval",
    default=1000,
    help="Interval in milliseconds between pings (default 1000)",
)
parser.add_argument(
    "-u",
    metavar="userid",
    default="sipping",
    help="User part of the From header (default sipping)",
)
parser.add_argument(
    "-i",
    metavar="ip",
    default="*",
    help="IP to send in the Via header (will TRY to get local IP by default)",
)
parser.add_argument(
    "-d",
    metavar="domain",
    default="gekk.info",
    help="Domain part of the From header (needed if your device filters based on domain)",
)
parser.add_argument(
    "-p", metavar="port", default=5060, help="Destination port (default 5060)"
)
parser.add_argument(
    "--ttl",
    metavar="ttl",
    default=70,
    help="Value to use for the Max-Forwards field (default 70)",
)
parser.add_argument(
    "-w",
    metavar="file",
    default="[[default]]",
    help="File to write results to. (default sipping-logs/[ip] - * to disable.",
)
parser.add_argument(
    "-t",
    metavar="timeout",
    default="1000",
    help="Time (ms) to wait for response (default 1000)",
)
parser.add_argument(
    "-c",
    metavar="count",
    default="0",
    help="Number of pings to send (default infinite)",
)
parser.add_argument(
    "-x", nargs="?", default=False, help="Print raw transmitted packets"
)
parser.add_argument("-X", nargs="?", default=False, help="Print raw received responses")
parser.add_argument(
    "-q",
    nargs="?",
    default=True,
    help="Do not print status messages (-x and -X ignore this)",
)
parser.add_argument("-S", nargs="?", default=True, help="Do not print loss statistics")
parser.add_argument(
    "--rtt",
    nargs="?",
    default=False,
    help="Only print rtt in ms on success, or 0.0 failure",
)
args = vars(parser.parse_args())

# populate data from commandline
# anything unspecified on the commandline is set to a default value by the parser
v_interval = int(args["I"])
v_fromip = args["i"]
v_sbc = args["host"]
v_userid = args["u"]
v_port = int(args["p"])
v_domain = args["d"]
v_ttl = args["ttl"]
v_timeout = int(args["t"])
v_rawsend = args["x"] is None
v_rawrecv = args["X"] is None
v_quiet = not args["q"]
v_nostats = not args["S"]
v_count = int(args["c"])
v_rtt = args["rtt"] is None

# did the user enter an IP?
if re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", v_sbc) is None:
    # the user entered a hostname; resolve it
    try:
        v_sbc = socket.getaddrinfo(v_sbc, 5060)[0][4][0]
    # socket.gaierror catches socket-specific exceptions but I think we can go without
    # except socket.gaierror as error:
    except Exception as exc:
        if v_rtt:
            print(0.0)
            sys.exit(1)
        # dns failure or no response
        print(exc)
        sys.exit(1)

if v_count == 0:
    v_count = sys.maxsize

if args["w"] == "[[default]]":
    if not os.path.exists("sipping-logs"):
        os.mkdir("sipping-logs")
    v_logpath = "sipping-logs/{ip}.csv".format(ip=v_sbc)
else:
    v_logpath = args["w"]

# if log output is enabled, ensure CSV has header
if v_logpath != "*":
    if not os.path.isfile(v_logpath):
        # create new CSV file and write header
        with open(v_logpath, "w", encoding="utf-8") as f_log:
            f_log.write("time,timestamp,host,latency,callid,response")


def generate_nonce(length=8):
    """Generate pseudorandom number for call IDs."""
    return "".join([str(random.randint(0, 9)) for i in range(length)])


# writes onscreen timestamps in a consistent format


def timef(timev=None):
    if timev is None:
        return datetime.now().strftime("%d/%m/%y %I:%M:%S:%f")
    return datetime.fromtimestamp(timev)


# register signal handler for ctrl+c since we're ready to start
signal.signal(signal.SIGINT, signal_handler)
if not v_quiet:
    print("Press Ctrl+C to abort")

# zero out statistics variables
v_recd = 0
v_lost = 0
v_longest_run = 0
v_last_run_loss = 0
v_current_run_loss = 0
last_lost = "never"
l_history = []
v_min = float("inf")
v_max = float("-inf")
v_iter = 0

# empty list of last 5 pings
l_current_results = []

# start the ping loop
##while 1:
while v_count > 0:
    v_count -= 1
    # create a socket
    skt_sbc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    skt_sbc.bind(("0.0.0.0", 0))
    skt_sbc.settimeout(v_timeout / 1000.0)
    # find out what port we're transmitting from to correlate the return packet
    v_localport = skt_sbc.getsockname()[1]
    # find out what IP we're sourcing from to populate the Via
    if v_fromip != "*":
        v_lanip = v_fromip
    else:
        v_lanip = socket.gethostbyname(socket.gethostname())

    # latency is calculated from this timestamp
    start = time.time()

    # create a random callid so we can identify the message in a packet capture
    v_callid = generate_nonce(length=10)

    v_branch = generate_nonce(length=10)

    # write the OPTIONS packet
    v_register_one = """OPTIONS sip:{domain} SIP/2.0
Via: SIP/2.0/UDP {lanip}:{localport};branch=z9hG4bK{branch}
To: "SIP Ping"<sip:{userid}@{domain}>
From: "SIP Ping"<sip:{userid}@{domain}>
Call-ID: {callid}
CSeq: 1 OPTIONS
Max-forwards: {ttl}
X-redundancy: Request
Content-Length: 0

""".format(
        domain=v_domain,
        lanip=v_lanip,
        userid=v_userid,
        localport=v_localport,
        callid=v_callid,
        ttl=v_ttl,
        branch=v_branch,
    )

    # print transmit announcement
    if not v_quiet and not v_rtt:
        print(
            (
                "> ({time}) Sending to {host}:{port} [id: {id}]".format(
                    host=v_sbc, port=v_port, time=timef(), id=v_callid
                )
            )
        )

    # if -x was passed, print the transmitted packet
    if v_rawsend:
        print(v_register_one)

    # send the packet
    skt_sbc.sendto(v_register_one.encode("utf-8"), (v_sbc, v_port))

    start = time.time()
    # wait for response
    try:
        # start a synchronous receive
        data, addr = skt_sbc.recvfrom(1024)  # buffer size is 1024 bytes

        # latency is calculated against this time
        end = time.time()
        diff = float("%.2f" % ((end - start) * 1000.0))

        # pick out the first line in order to get the SIP response code
        v_response = data.split("\n".encode("utf-8"))[0]

        # print success message and response code
        if v_rtt:
            print(diff)
        elif not v_quiet:
            print(
                (
                    "< ({time}) Reply from {host} ({diff}ms): {response}".format(
                        host=addr[0], diff=diff, time=timef(), response=v_response
                    )
                )
            )

        # if -X was passed, print the received packet
        if v_rawrecv:
            print(data)

        # log success
        l_current_results.append(
            "{time},{timestamp},{host},{diff},{id},{response}".format(
                host=addr[0],
                diff=diff,
                time=timef(),
                timestamp=time.time(),
                id=v_callid,
                response=v_response,
            )
        )

        # update statistics
        l_history.append(diff)
        if len(l_history) > 200:
            l_history = l_history[1:]
        v_min = min(v_min, diff)
        v_max = max(v_max, diff)
        v_recd = v_recd + 1
        if v_current_run_loss > 0:
            v_last_run_loss = v_current_run_loss
            v_longest_run = max(v_longest_run, v_last_run_loss)
            v_current_run_loss = 0
    except socket.timeout:
        # timed out; print a drop
        if v_rtt:
            print(0.0)
        elif not v_quiet:
            print(
                (
                    "X ({time}) Timed out waiting for response from {host}".format(
                        host=v_sbc, time=timef()
                    )
                )
            )
        # log a drop
        l_current_results.append(
            "{time},{timestamp},{host},drop,{id},drop".format(
                host=v_sbc, time=timef(), timestamp=time.time(), id=v_callid
            )
        )

        # increment statistics
        v_lost = v_lost + 1
        v_current_run_loss = v_current_run_loss + 1

    v_iter = v_iter + 1
    # if it's been five packets, print stats and write logfile
    if v_iter > 4:
        # print stats to screen
        if not v_nostats:
            printstats()

        # if logging is enabled, append stats to logfile
        if v_logpath != "*":
            with open(v_logpath, "a", encoding="utf-8") as f_log:
                f_log.write("\n" + ("\n".join(l_current_results)))
        l_current_results = []

        v_iter = 0

    # pause for user-requested interval before sending next packet
    if v_count > 0:
        time.sleep(v_interval / 1000.0)
if v_lost > 0:
    sys.exit(1)
