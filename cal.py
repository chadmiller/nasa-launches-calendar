
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache

from icalendar import Event, Calendar

import urllib2
import logging
import re
import json

from datetime import date, datetime, timedelta
import time

import icalendar
from BeautifulSoup import BeautifulSoup, NavigableString

from google.appengine.api import memcache

class About(webapp.RequestHandler):

    def get(self):
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write(open(__file__).read())

class Statistics(webapp.RequestHandler):

    def get(self):
        self.response.headers['Content-Type'] = 'application/json'
        self.response.out.write(json.dumps(memcache.get_stats()))


def all_strings(e, n=0):
    if isinstance(e, NavigableString):
        return e.string
    else:
        combined = list()
        for sub in e.contents:
            combined.append(all_strings(sub, n+1))
        return "".join(combined)

def data_to_event(data):
    if "Date" not in data:
        logging.info("no date in %r" % (data,))
        return

    try:
        d = interpret_date(data)
    except ValueError, e:
        logging.warn("%s  Skipping %s" % (e, data,))
        return

    assert isinstance(d, datetime) or isinstance(d, date), d

    try:
        description_key = ""
        description_key = [dk for dk in data.keys() if dk.endswith("Description")][0]
    except IndexError, e:
        logging.info("data has no description, so will try for mission: %s", data)

    if not description_key:
        description_key = [dk for dk in data.keys() if dk.endswith("Mission")][0]

    event = Event()
    event.add('summary', "%s launch from %s" % (data.get("Mission", "unlisted"), data.get("Launch Site", "unlisted site")))
    event.add('description', data.get(description_key) + " //  last verified " + datetime.now().isoformat()[:-10])
    event.add('dtstamp', datetime.now())  # todo: make this the modtime of page
    if type(d) == datetime:
        event.add('dtstart', d)
    else:
        event.add('dtstart;value=date', icalendar.vDate(d).ical())

    if type(d) == datetime:
        event.add('dtend', d + timedelta(minutes=10))
    else:
        event.add('dtend;value=date', icalendar.vDate(d).ical())
    event["uid"] = "%s@launches.ksc.nasa.gov" % (data.get("Mission", "MISSION").replace(" ", "-").lower(),)
    return event
    

class EventsListingCal(webapp.RequestHandler):

    def get(self):
        self.response.headers['Content-Type'] = 'text/calendar'

        calendar = memcache.get("ksc-calendar")
        if calendar:
            self.response.out.write(calendar)
            return

        cal = Calendar()
        cal.add('version', '2.0')
        cal.add('prodid', '-//Kennedy Space Center launches by Chad//NONSCML//EN')
        cal.add('X-WR-CALID', '8293bcab-1b27-44dd-8a3c-2bb045888629')
        cal.add('X-WR-CALNAME', 'KSC launches by Chad')
        cal.add('X-WR-CALDESC', "NASA publishes a web page of scheduled launches, but an iCalendar/RFC5545 feed would be so much better and useful.  So, ( https://chad.org/ ) Chad made one.  Enjoy!")
        cal.add('X-WR-TIMEZONE', 'US/Eastern')

        launch_calendar_id = 6089
        two_months_ago = datetime.utcnow() + timedelta(days=-60)
        one_year_from_now = datetime.utcnow() + timedelta(days=365)

        index_json = urllib2.urlopen("https://www.nasa.gov/api/1/query/calendar.json?timeRange={0}--{1}&calendars={2}".format(two_months_ago.strftime("%Y%m%d0000"), one_year_from_now.strftime("%Y%m%d0000"), launch_calendar_id))
        index = json.load(index_json)

        for index_event in index["calendarEvents"]:
            assert index_event["type"] == "calendar_event"
            ev_url = "https://www.nasa.gov/api/1/query/node/{0}.json?{1}".format(index_event["nid"], index_event["urlQuery"])
            event_json = urllib2.urlopen(ev_url)
            event_info = json.load(event_json)

            if "eventDate" in event_info["calendarEvent"]:
                for i, event_occurance in enumerate(event_info["calendarEvent"]["eventDate"]):
                    event = Event()

                    event.add('uid', event_info["calendarEvent"]["uuid"] + "_" + str(i))
                    event.add('summary', event_info["calendarEvent"]["title"])
                    event.add('description', event_info["calendarEvent"]["description"])
                    event.add('dtstamp', datetime.fromtimestamp(int(event_info["calendarEvent"]["changed"])))

                    date_start = datetime.strptime(event_occurance["value"][:-5], "%Y-%m-%dT%H:%M:%S-")
                    date_end = datetime.strptime(event_occurance["value2"][:-5], "%Y-%m-%dT%H:%M:%S-")
                    if event_occurance["date_type"] == "date":
                        event.add("dtstart;value=date", icalendar.vDate(date_start).ical())
                        event.add("dtend;value=date", icalendar.vDate(date_end).ical())
                    else:
                        event.add("dtstart", date_start)
                        event.add("dtend", date_end)

                    cal.add_component(event)



        self.response.out.write(cal.as_string())
        for retry in range(3):
            if not memcache.add("ksc-calendar", cal.as_string(), 60*5):
                logging.warn("Failed to add data to Memcache.")
                time.sleep(0.5)
            else:
                break


app = webapp.WSGIApplication(
        [
            ('/ksc-launches.ics', EventsListingCal),
            ('/', EventsListingCal),
            ('/statistics', Statistics),
            ('/about', About)
        ], debug=True)

