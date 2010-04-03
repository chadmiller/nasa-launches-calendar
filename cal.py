
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import memcache

from icalendar import Event, Calendar

import urllib
import logging
try:
    from django.utils import simplejson as json
except ImportError:
    logging.exception("no django utils simplejson")
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

def interpret_date(data):
    if data.get("year") is None:
        raise ValueError("no data")

    if "Launch Time" in data:
        timezone = data["Launch Time"].split()[-1]
        if timezone == "EDT":
            pass
        elif timezone == "EST":
            pass
        else:
            raise ValueError("tz is " + repr(timezone))

        time = "%s %s %04d" % (" ".join(data["Launch Time"].replace(".", "").upper().split()[:-1]), data["Date"].strip(" +*").replace(".", "").replace("Sept", "Sep"), data["year"])
        try:
            d = datetime.strptime(time, "%I:%M %p %b %d %Y")
        except ValueError:
            d = datetime.strptime(time, "%I:%M %p %B %d %Y")

    else:
        time = "%s %04d" % (data["Date"].strip(" +*").replace(".", "").replace("Sept", "Sep"), data["year"])
        try:
            d = datetime.strptime(time, "%b %d %Y").date()
        except ValueError:
            try:
                d = datetime.strptime(time, "%B %d %Y").date()
            except ValueError, e:
                self.response.out.write(str(e))
                return
        
    return d

def data_to_event(data):
    if "Date" not in data:
        logging.warn("no date in %r" % (data,))
        return

    try:
        d = interpret_date(data)
    except ValueError, e:
        logging.warn("%s  Skipping %s" % (e, data,))
        return

    assert isinstance(d, datetime) or isinstance(d, date), d

    description_key = [dk for dk in data.keys() if dk.endswith("Description")][0]

    event = Event()
    event.add('summary', "%s launch from %s" % (data.get("Mission", "(?)"), data.get("Launch Site", "")))
    event.add('description', data.get(description_key))
    event.add('dtstart', d)
    event.add('dtend', d)
    event.add('dtstamp', d)
    event["uid"] = "%s@launches.ksc.nasa.gov" % (data.get("Mission", "MISSION").replace(" ", "-").lower(),)
    return event
    

class EventsListingCal(webapp.RequestHandler):

    def __init__(self):
        super(EventsListingCal, self).__init__()


    def get(self):
        self.response.headers['Content-Type'] = 'text/calendar'

        calendar = memcache.get("ksc-calendar")
        if calendar:
            self.response.out.write(calendar)
            

        cal = Calendar()
        cal.add('prodid', '-//Kennedy Space Center launches by Chad//NONSCML//EN')
        cal.add('version', '2.0')
        cal.add('X-WR-CALNAME', 'KSC launches by Chad')
        cal.add('X-WR-TIMEZONE', 'US/Eastern')
        nasa_html = urllib.urlopen("http://www.nasa.gov/missions/highlights/schedule.html").read()
        doc = BeautifulSoup(nasa_html).find("div", {"class": "white_article_wrap_detail text_adjust_me"})

        year = None
        data = { "year": year }
        for sib in doc.findAll(recursive=False)[0].findAll(recursive=False):
            if sib.name == "center":
                year = int(sib.b.text.split(" ")[0])
                data["year"] = year
            elif sib.name == "b":
                key = sib.text.strip(" :").encode("utf8")
                value = all_strings(sib.nextSibling).strip().encode("utf8")
                if value == "":
                    value = all_strings(sib.nextSibling.nextSibling).strip().encode("utf8")
                    if value.endswith("-"):
                        value += " "
                        value += all_strings(sib.nextSibling.nextSibling.nextSibling).strip().encode("utf8")

# Legend: + Targeted For | * No Earlier Than (Tentative) | ** To Be Determined 
                if key == "Date" and "**" in value:
                    logging.info("Date is TBD  %r" % (value,))
                    continue
                    
                data[key] = value
            elif sib.name == "br":
                if not isinstance(sib.nextSibling, NavigableString) and sib.nextSibling.name == "br":

                    e = data_to_event(data)
                    if e:
                        cal.add_component(e)
                    data = { "year": year }
            else:
                pass
        
        e = data_to_event(data)
        if e:
            cal.add_component(e)

        self.response.out.write(cal.as_string())
        if not memcache.add("ksc-calendar", cal.as_string(), 60*5):
            logging.warn("Failed to add data to Memcache.")


        

application = webapp.WSGIApplication(
        [
            ('/', EventsListingCal),
            ('/statistics', Statistics),
            ('/about', About)
        ], debug=True)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()
