#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys, time, urllib, json
from datetime import datetime
from httplib import BadStatusLine
from urllib2 import URLError
from ssl import SSLError
import pymongo, socket
from multiprocessing import Process, Queue
from twitter import Twitter, TwitterStream, OAuth, OAuth2, TwitterHTTPError
from tweets import prepare_tweets

def log(typelog, text):
    sys.stderr.write("[%s] %s: %s\n" % (datetime.now(), typelog, text))

def depiler(pile, db, debug=False):
    while True:
        todo = []
        while not pile.empty():
            todo.append(pile.get())
        save = prepare_tweets(todo)
        for t in save:
             tid = db.save(t)
        if debug and save:
            log("DEBUG", "Saved %s tweets in MongoDB" % len(save))
        time.sleep(2)

real_min = lambda x, y: min(x, y) if x else y
date_to_time = lambda x: time.mktime(datetime.strptime(x[:16], "%Y-%m-%d %H:%M").timetuple())

def streamer(pile, streamco, keywords, timed_keywords, debug=False):
    while True:
        ts = time.time()
        log('INFO', 'Starting stream track')

        # handle timed keywords and find first date when to stop
        end_time = None
        for keyw, planning in timed_keywords.items():
            for times in planning:
                t0 = date_to_time(times[0])
                t1 = date_to_time(times[1])
                if t0 < ts < t1:
                    keywords.append(keyw)
                    end_time = real_min(end_time, t1)
                    break
                elif t0 > ts:
                    end_time = real_min(end_time, t0)

        try:
            streamiter = streamco.statuses.filter(track=",".join([k.lstrip('@').strip().lower() for k in keywords]).encode('utf-8'), filter_level='none', stall_warnings='true')
        except (TwitterHTTPError, BadStatusLine, URLError, SSLError) as e:
            log("WARNING", "Stream connection could not be established, retrying in 2 secs (%s: %s)" % (type(e), e))
            time.sleep(2)
            continue

        try:
            for msg in streamiter:
                if end_time and end_time < time.time():
                    log("INFO", "Reached time to update list of keywords")
                    break
                if not msg:
                    continue
                if msg.get("disconnect") or msg.get("hangup"):
                    log("WARNING", "Stream connection lost: %s" % msg)
                    break
                if msg.get("timeout"):
                    continue
                if msg.get('text'):
                    pile.put(dict(msg))
                    if debug:
                        log("DEBUG", "[stream] +1 tweet")
                else:
                    log("INFO", "Got special data: %s" % str(msg))
        except (TwitterHTTPError, BadStatusLine, URLError, SSLError, socket.error) as e:
            log("WARNING", "Stream connection lost, reconnecting in a sec... (%s: %s)" % (type(e), e))

        if debug:
            log("DEBUG", "Stream stayed alive for %sh" % str((time.time()-ts)/3600))
        time.sleep(2)

chunkize = lambda a, n: [a[i:i+n] for i in xrange(0, len(a), n)]

def get_twitter_rates(conn):
    rate_limits = conn.application.rate_limit_status(resources="search")['resources']['search']['/search/tweets']
    return rate_limits['reset'], rate_limits['limit'], rate_limits['remaining']

def searcher(pile, searchco, keywords, timed_keywords, debug=False):
    try:
        next_reset, max_per_reset, left = get_twitter_rates(searchco)
    except:
        log("ERROR", "Connecting to Twitter API via OAuth2 sign, could not get rate limits")
        sys.exit(1)
    keywords = [urllib.quote(k.encode('utf-8').replace('@', 'from:'), '') for k in keywords]
    queries = [" OR ".join(a) for a in chunkize(keywords, 3)]
    now = time.time()
    lastweek = now - 60*60*24*7
    for keyw, planning in timed_keywords.items():
        pass
        #for times in planning:
        #    t0 = date_to_time(times[0])
        #    t1 = date_to_time(times[1])
        #    if last_week < t0 < now or last_week < t1 < now:
        #       queries.append((urllib.quote(keyw.encode('utf-8').replace('@', 'from:'), ''), planning))
        #       break

    timegap = 1 + len(queries)
    queries_since_id = [0 for _ in queries]
    while True:
        if time.time() > next_reset:
            try:
                next_reset, _, left = get_twitter_rates(searchco)
            except:
                next_reset += 15*60
                left = max_per_reset
        if not left:
            log("WARNING", "Stalling search queries with rate exceeded for the next %s seconds" % max(0, int(next_reset - time.time())))
            time.sleep(timegap + max(0, next_reset - time.time()))
            continue
        if debug:
            log("DEBUG", "Starting search queries with %d remaining calls for the next %s seconds" % (left, int(next_reset - time.time())))
        for i, query in enumerate(queries):

            # TODO: handle tuple queries with planning

            since = queries_since_id[i]
            max_id = 0
            while left:
                args = {'q': query, 'count': 100, 'include_entities': True}
                if max_id:
                    args['max_id'] = str(max_id)
                if queries_since_id[i]:
                    args['since_id'] = str(queries_since_id[i])
                try:
                    res = searchco.search.tweets(**args)
                except (TwitterHTTPError, BadStatusLine, URLError, SSLError) as e:
                    log("WARNING", "Search connection could not be established, retrying in 2 secs (%s: %s)" % (type(e), e))
                    time.sleep(2)
                    continue
                tweets = res.get('statuses', [])
                left -= 1
                if not len(tweets):
                    break
                if debug:
                    log("DEBUG", "[search] +%d tweets (%s)" % (len(tweets), query))
                for tw in tweets:
                    tid = long(tw.get('id_str', str(tw.get('id', ''))))
                    if not tid:
                        continue
                    if since < tid:
                        since = tid + 1
                    if not max_id or max_id > tid:
                        max_id = tid - 1
                    pile.put(dict(tw))
            queries_since_id[i] = since
        time.sleep(max(timegap, next_reset - time.time() - 2*left))

if __name__=='__main__':
    try:
        with open('config.json') as confile:
            conf = json.loads(confile.read())
        oauth = OAuth(conf['twitter']['oauth_token'], conf['twitter']['oauth_secret'], conf['twitter']['key'], conf['twitter']['secret'])
        oauth2 = OAuth2(bearer_token=json.loads(Twitter(api_version=None, format="", secure=True, auth=OAuth2(conf['twitter']['key'], conf['twitter']['secret'])).oauth2.token(grant_type="client_credentials"))['access_token'])
        SearchConn = Twitter(domain="api.twitter.com", api_version="1.1", format="json", auth=oauth2, secure=True)
        StreamConn = TwitterStream(domain="stream.twitter.com", api_version="1.1", auth=oauth, secure=True, block=False, timeout=10)
    except Exception as e:
        log('ERROR', 'Could not initiate connections to Twitter API: %s %s' % (type(e), e))
        sys.exit(1)
    try:
        db = pymongo.Connection(conf['mongo']['host'], conf['mongo']['port'])[conf['mongo']['db']]
        coll = db['tweets']
        coll.ensure_index([('_id', pymongo.ASCENDING)], background=True)
        coll.ensure_index([('timestamp', pymongo.ASCENDING)], background=True)
    except:
        log('ERROR', 'Could not initiate connection to MongoDB')
        sys.exit(1)

    pile = Queue()
    depile = Process(target=depiler, args=(pile, coll, conf['debug']))
    depile.daemon = True
    depile.start()
    stream = Process(target=streamer, args=(pile, StreamConn, conf['keywords'], conf['time_limited_keywords'], conf['debug']))
    stream.daemon = True
    stream.start()
    search = Process(target=searcher, args=(pile, SearchConn, conf['keywords'], conf['time_limited_keywords'], conf['debug']))
    search.start()
    depile.join()

