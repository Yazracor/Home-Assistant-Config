#!/usr/bin/env python3
"""Calibrate a local lux clear-sky reference against hourly public ERA5 data.

Recorder statistics cover [start, start + 1h). Open-Meteo radiation at time t
is the preceding hour, so weather timestamps are shifted back one hour.
Solar elevation uses the NOAA fractional-year approximation (UTC), averaged
at four points per hour for the Haurwitz clear-sky horizontal reference.
This calibrates a lux proxy; neither cloud percentage nor a radiometer.
"""
import argparse, hashlib, math, sqlite3, json, datetime, statistics, urllib.request
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--database', default='home-assistant_v2.db')
parser.add_argument('--weather-json', type=Path, required=True)
parser.add_argument('--fetch', action='store_true', help='Download public ERA5 data into --weather-json')
parser.add_argument('--output', type=Path, default=Path('docs/hitzeschutz_solar_kalibrierung.json'))
args = parser.parse_args()
WEATHER_URL = ('https://archive-api.open-meteo.com/v1/archive?latitude=50.1026602'
               '&longitude=8.2715918&start_date=2026-05-30&end_date=2026-10-04'
               '&hourly=cloud_cover,shortwave_radiation,direct_normal_irradiance&timezone=UTC&models=era5')
if args.fetch:
    with urllib.request.urlopen(WEATHER_URL, timeout=60) as response:
        args.weather_json.write_bytes(response.read())
LAT,LON=50.1026602,8.2715918

def altitude(ts):
 t=datetime.datetime.fromtimestamp(ts,datetime.UTC); g=2*math.pi/365*(t.timetuple().tm_yday-1+(t.hour-12)/24)
 eq=229.18*(.000075+.001868*math.cos(g)-.032077*math.sin(g)-.014615*math.cos(2*g)-.040849*math.sin(2*g))
 dec=.006918-.399912*math.cos(g)+.070257*math.sin(g)-.006758*math.cos(2*g)+.000907*math.sin(2*g)-.002697*math.cos(3*g)+.00148*math.sin(3*g)
 ha=math.radians((t.hour*60+t.minute+t.second/60+eq+4*LON)/4-180)
 s=math.sin(math.radians(LAT))*math.sin(dec)+math.cos(math.radians(LAT))*math.cos(dec)*math.cos(ha)
 return math.degrees(math.asin(s))
def clear(ts):
 s=max(0,math.sin(math.radians(altitude(ts))))
 return 1098*s*math.exp(-.059/s) if s else 0
c=sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True)
meta = c.execute("select id from statistics_meta where statistic_id='sensor.aussenbereich_wetterstation_helligkeit'").fetchone()
if meta is None: raise SystemExit('No illuminance statistics found')
stats={int(t): (mean,mx) for t,mean,mx in c.execute('select start_ts,mean,max from statistics where metadata_id=?', (meta[0],))}
weather=json.loads(args.weather_json.read_text()); w=weather['hourly']; rows=[]
for i,t in enumerate(w['time']):
 end=datetime.datetime.fromisoformat(t).replace(tzinfo=datetime.UTC).timestamp(); start=int(end-3600)
 if start not in stats or any(w[k][i] is None for k in ('cloud_cover','shortwave_radiation','direct_normal_irradiance')): continue
 mean,mx=stats[start]; elev=altitude(start+1800)
 ref=sum(clear(start+x) for x in (450,1350,2250,3150))/4
 if elev>=5 and mean>0 and ref>=50: rows.append({'ts':start,'elev':elev,'lux':mean,'ref':ref,'cloud':w['cloud_cover'][i],'dni':w['direct_normal_irradiance'][i],'ghi':w['shortwave_radiation'][i]})
cs=[r for r in rows if r['cloud']<=20 and r['dni']>=400]
print('daylight',len(rows),'clear',len(cs))
for lo,hi in ((5,15),(15,25),(25,35),(35,45),(45,65)):
 a=[r['lux']/r['ref'] for r in cs if lo<=r['elev']<hi]
 print(lo,hi,'n',len(a),'median',round(statistics.median(a),2) if a else None)
recent_start = datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC).timestamp()
recent_clear = [r for r in cs if r['ts'] >= recent_start]
ratios=sorted(r['lux']/r['ref'] for r in recent_clear)
scale=statistics.median(ratios); print('scale',scale,'range',ratios[0],ratios[-1])
for cloudlo,cloudhi in ((0,20),(20,60),(60,90),(90,101)):
 rr=[r for r in rows if r['ts'] >= recent_start and cloudlo<=r['cloud']<cloudhi]; values=[r['lux']/(r['ref']*scale) for r in rr]; print('cloud',cloudlo,cloudhi,'n',len(rr),'index median',round(statistics.median(values),3) if values else None)
for k in (.3,.4,.45,.5,.6):
 pred=[r for r in rows if r['ts'] >= recent_start and r['lux']/(r['ref']*scale)>=k]
 print('cutoff',k,'n',len(pred),'dni>200',round(sum(r['dni']>=200 for r in pred)/len(pred),3))
cloud_groups = []
for lower, upper in ((0,20),(20,60),(60,90),(90,101)):
    selected = [r for r in rows if r['ts'] >= recent_start and lower <= r['cloud'] < upper]
    cloud_groups.append({'cloud_range_percent': [lower, upper], 'hours': len(selected),
                         'median_lux_index': statistics.median(r['lux']/(r['ref']*scale) for r in selected)})
altitude_groups = []
for lower, upper in ((5,15),(15,25),(25,35),(35,45),(45,65)):
    selected = [r for r in cs if lower <= r['elev'] < upper]
    altitude_groups.append({'elevation_range_degrees': [lower, upper], 'clear_hours': len(selected),
                            'median_lux_per_watt': statistics.median(r['lux']/r['ref'] for r in selected) if selected else None})
split = datetime.datetime(2026, 9, 15, tzinfo=datetime.UTC).timestamp()
train = [r for r in recent_clear if r['ts'] < split]
holdout = [r for r in cs if r['ts'] >= split]
train_scale = statistics.median(r['lux']/r['ref'] for r in train)
validation = {'training_clear_hours': len(train), 'training_lux_per_watt': train_scale,
              'holdout_period': ['2026-09-15', '2026-10-04'], 'holdout_clear_hours': len(holdout),
              'holdout_median_index': statistics.median(r['lux']/(r['ref']*train_scale) for r in holdout)}
report = {
    'source_url': WEATHER_URL, 'weather_sha256': hashlib.sha256(args.weather_json.read_bytes()).hexdigest(),
    'requested_location': {'latitude': LAT, 'longitude': LON},
    'weather_grid_location': {k:weather[k] for k in ('latitude','longitude','elevation')},
    'period': ['2026-05-30', '2026-10-04'], 'hour_alignment': 'Recorder start = weather timestamp minus 1h',
    'method': 'Median local hourly mean lux / hourly mean Haurwitz irradiance; NOAA solar position approximation',
    'clear_selection': {'maximum_cloud_percent': 20, 'minimum_dni_w_m2': 400, 'minimum_elevation_degrees': 5},
    'daylight_hours': len(rows), 'clear_hours': len(cs), 'calibration_clear_hours': len(recent_clear),
    'calibration_period': ['2026-09-01','2026-10-04'],
    'calibration_daylight_hours': sum(r['ts'] >= recent_start for r in rows), 'lux_per_watt': scale,
    'monthly_clear_lux_per_watt': {str(month): statistics.median(r['lux']/r['ref'] for r in cs if datetime.datetime.fromtimestamp(r['ts'],datetime.UTC).month == month) for month in range(6,11)},
    'altitude_groups': altitude_groups, 'cloud_groups': cloud_groups, 'temporal_validation': validation,
    'limitations': ['ERA5 grid data are modeled and not measured at the window.',
                   'Lux reference is a proxy, not an irradiance measurement or cloud percentage.',
                   'Low-sun and winter calibration coverage is limited; fall back to existing lux threshold below 5 degrees.',
                   'Strong summer-to-autumn drift: use recent autumn data, not a common annual coefficient.',
                   'Calibration coefficients vary with solar altitude and local sensor exposure.']
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
print('Report:', args.output)
