#! /usr/bin/env python3

import re
import sys
import argparse
from collections import defaultdict

# TODO: support rollover timestamps (23:59:59.999999 -> 00:00:00.000000)
# TODO: support multi process single log file
# TODO: flatten multi process

parser= argparse.ArgumentParser (description='''Convert l/strace logs into csv.
    Those tools must be run with the -ff and -T options.''')
group= parser.add_mutually_exclusive_group (required=True)
group.add_argument ('-r', '--relative', action='store_true',
                    help= '''The log files have relative timestamps;
                             that is, they were generated with l/strace's -r option''')
group.add_argument ('-t', '--timestamp', action='count', default=0,
                     help= '''The log files have absolute timestamps;
                              that is, they were generated with some amount of
                              l/strace's -t option, two minimum''')
parser.add_argument ('-c', '--histogram', action='store_true',
                     help='''Make the output to be in the form
                            'syscall,count,min,avg,max,total'.''')
parser.add_argument ('logfiles', metavar='logfile', nargs='+')
args= parser.parse_args ()

# -r
#      0.000400 close(2)                  = 0 <0.000158>
#   0.000611 fclose(0x7ff8faf07060)       = 0 <0.000763>
# -t (useless)
# 10:57:06 close(2)                       = 0 <0.000154>
# 10:49:57 fclose(0x7feba5777060)         = 0 <0.000611>
# -tt
# 10:57:58.768568 close(2)                = 0 <0.000178>
# 10:50:47.187083 fclose(0x7f2604f71060)  = 0 <0.000502>
# -ttt
# 1420624694.401959 close(2)              = 0 <0.000149>
# 1420624321.631293 fclose(0x7f206c3b5060) = 0 <0.000667>

if args.timestamp==1:
    parser.error ('''l/strace's -t option generates a useless timestamp; please regenerate the logfile with either -r, -tt or -ttt.''')

#                           10:      50:     47.187083
#                                    1420624694.401959
timestamp_parser= '(?:(\d{2})\:(\d{2})\:)?(\d+\.\d{6})'
#              libpagemanager.so.1
caller_parser= '.*'
#
funcname_parser= '([A-Za-z0-9_]+)'
params_parser= '.*'
result_parser= '[^ ]+'
time_parser= '\<(\d+\.\d{6})\>'

# 16:08:17.082102 libpagemanager.so.1->mdb_env_create(0x6469c8, 0x7ff1e7c0d250, 0x646a48, 0x7ff1e7e41ea0) = 0 <0.000181>
normal= re.compile ('\s*%s +(?:%s\-\>)?%s\(%s\= %s %s' % (timestamp_parser, caller_parser, funcname_parser,
                                                     params_parser, result_parser, time_parser))
# 16:08:17.192471 libDocumentAccess-Mh.so.1->MF_DeleteCollection(0x6490a8, 55, 0x6490a8, 0x7ff1e83c44e0 <unfinished ...>
unfinished= re.compile ('\s*%s +(?:%s\-\>)?%s\(%s\<unfinished \.\.\.\>' % (timestamp_parser, caller_parser,
                                                                      funcname_parser, params_parser))
# 16:08:17.203365 <... MF_DeleteCollection resumed> )                                                     = 0x7ea000000000 <0.001550>
resumed= re.compile ('\s*%s +\<\.\.\. %s resumed\>.*\= %s %s' % (timestamp_parser, funcname_parser,
                                                                 result_parser, time_parser))
# 11:44:55.470482  libpagemanager.so.1->mdb_txn_begin(0x646a80, 0, 0, 0x7fff6d7769f8 <no return ...>
# the point of...
no_return= re.compile ('\s*%s +(?:%s\-\>)?%s\(%s\<no return \.\.\.\>' % (timestamp_parser, caller_parser,
                                                                    funcname_parser, params_parser))
# anything, really, most likely
# 11:46:38.322997 +++ killed by SIGTERM +++
just_time= re.compile ('\s*%s' % timestamp_parser)

width= len (args.logfiles)

# holds the histogram in the form
# hitogram[pid][fun] = [count, min, max, total]
# itś a list because itś easier at the end to just modify this and print
# avg is skipped because it's calculable as total/count
histogram= defaultdict (dict)

def process_line (fun, start, time, i):
    if args.histogram:
        time= float (time)
        if histogram[i].get (fun, None) is None:
            histogram[i][fun]= [ 1, time, time, time ]  # time and time again :)
        else:
            count, mn, mx, total= histogram[i][fun]
            count+= 1
            if time<mn:
                mn= time
            if time>mx:
                mx= time
            total+= time

            histogram[i][fun]= [ count, mn, mx, total ]
    else:
        write_line (fun, start, time, i)

def write_line (fun, start, time, i):
    data= [ "" for n in range (width+2) ]
    data[0]= fun
    data[1]= start
    data[i+2]= time

    print (",".join (data))

def hms_mic2s_mic (h, m, s):
    if h is None:
        h= 0
    if m is None:
        m= 0

    return int (h)*3600+int (m)*60+float (s)

# TODO:
# min_time= float (sys.argv[1])
min_time= 0.0

# print header
if args.histogram:
    print (','.join ([ 'fun,count,min,avg,max,total' ]*width))
else:
    print ('fun,start_time,'+','.join (args.logfiles))  # TODO: use PIDs if available

for i, f in enumerate (args.logfiles):
    start_times= {}

    for line in open (f):
        g= normal.match (line)
        if g is not None:
            h, m, start, fun, time= g.groups ()

            if float (time)>=min_time:
                process_line (fun, repr (hms_mic2s_mic (h, m, start)), time, i)

            continue

        g= unfinished.match (line)
        if g is not None:
            h, m, start, level, fun= g.groups ()

            start_times[(fun, len (level))]= hms_mic2s_mic (h, m, start)
            continue

        g= resumed.match (line)
        if g is not None:
            h, m, start, level, fun, time= g.groups ()
            start= start_times.pop ((fun, len (level)))

            if time>=min_time:
                process_line (fun, repr (start), time, i)

            continue

        g= no_return.match (line)
        if g is not None:
            h, m, start, fun= g.groups ()

            start_times[(fun, -1)]= hms_mic2s_mic (h, m, start)
            continue

        # TODO: 1420626429.826269 exit_group(0)         = ?

        # print "malformed line: %s" % line

        # save it to complete unfinished/no return'ed functions
        last_line= line

    g= just_time.match (last_line)
    h, m, end, = g.groups ()
    for (fun, _), start in start_times.items ():
        time= hms_mic2s_mic (h, m, end)-start

        if time>=min_time:
            process_line (fun, repr (start), str(time), i)

if args.histogram:
    # we can do this only once we collected all the data
    funcs= set ([ keys
                      for i in histogram.keys()
                          for keys in histogram[i].keys () ])

    for fun in sorted (funcs):
        data= []
        for i in range (width):
            # count,min,max,total
            inner_data= histogram[i].get (fun, [0, 0, 0, 0])
            # between min ([1]) and max ([2])
            try:
                inner_data.insert (2, inner_data[-1]/inner_data[0])
            except ZeroDivisionError:
                inner_data.insert (2, 0)

            data.extend ([ fun, str (inner_data[0]) ]+
                         [ "%15.8f" % d for d in inner_data[1:] ])

        print (','.join (data))

    print ('''We recommend that you organize the chart as follows:
* Count goes in a secondary Y axis.
* The primary Y axis is logarithmic, with a lower value of 0.000001.
* You could sort the rows by name, count or total time.''', file=sys.stderr)
