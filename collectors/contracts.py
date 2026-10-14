"""Required RUN_DIR collector interfaces. Legacy Bash implementations remain."""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, date, timedelta
from email.utils import parsedate_to_datetime
from pipeline_common import ROOT, Invalid, canonical, load, policy, receipt, require, utc
from processing.evidence_contract import fixture


def fetch(source):
    request = urllib.request.Request(source['url'], headers={'User-Agent': 'PS04-Research-Collector/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def rss_records(source, raw, as_of):
    root = ET.fromstring(raw)
    output = []
    for entry in root.findall('.//channel/item'):
        title = (entry.findtext('title') or '').strip()
        link = (entry.findtext('link') or '').strip()
        pub = entry.findtext('pubDate')
        if not title:
            continue
        when = parsedate_to_datetime(pub) if pub else None
        if when is not None:
            # RFC -0000 is UTC with the publisher's local zone unknown.
            # Match a complete date so an unknown zone plus trailing -0000
            # cannot exploit the standard parser's permissive token handling.
            if when.tzinfo is None and re.fullmatch(
                r'(?i)(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+)?'
                r'\d{1,2}\s+[a-z]{3}\s+\d{4,}\s+\d{2}:\d{2}(?::\d{2})?\s+-0000\s*', pub.strip()
            ):
                when = when.replace(tzinfo=timezone.utc)
            if when.tzinfo is None:
                raise Invalid('Publisher date has no timezone')
            when = when.astimezone(timezone.utc)
        published = when.isoformat().replace('+00:00', 'Z') if when is not None else None
        media = None
        if source['kind'] == 'podcast':
            enclosure = entry.find('enclosure')
            if enclosure is None or not enclosure.get('url'):
                continue
            if when is not None and not as_of-timedelta(days=29) <= when.date() <= as_of:
                continue
            media = enclosure.get('url')
            identity = entry.findtext('guid') or link or media
            item_id = 'podcast:' + hashlib.sha256((source['source_id']+':'+identity).encode()).hexdigest()[:20]
            link = link or media
        else:
            if not link:
                continue
            item_id = 'feed:' + hashlib.sha256(link.encode()).hexdigest()[:16]
        output.append(dict(item_id=item_id, source_id=source['source_id'], publisher_id=source['publisher_id'],
            kind=source['kind'], title=title, url=link, published_at=published, retrieved_at=utc(),
            media_url=media, discovery_method='podcast_rss' if media else 'rss'))
    return output


def collect(folder, kind):
    started = utc();output=[];errors=[];code=0;tool='Python RSS / yt_dlp';attempted=False;received=False
    try:
        run=load(folder/'run.json')
        if run.get('contract_version') == 2:
            policy(folder)
            sources=load(folder/'config/sources.json')
        else:
            sources=load(folder/'sources.json')
        chosen=[x for x in sources if x['kind']==kind]
        require(bool(chosen), 'No configured sources for '+kind)
        mock=fixture(folder, 'collector_'+kind+'.json')
        if mock is not None:
            output=mock['output'];errors=mock.get('errors',[]);tool='EXPLICIT OFFLINE COLLECTOR FIXTURE'
        else:
            require(os.environ.get('PS04_ALLOW_COLLECTION')=='1', 'Network collection requires separate explicit authorization')
            as_of=date.fromisoformat(run['as_of_date'])
            for source in chosen:
                try:
                    attempted=True
                    if kind=='youtube':
                        result=subprocess.run([sys.executable,'-m','yt_dlp','--js-runtimes','node','--skip-download',
                            '--dump-single-json','--no-playlist',source['url']],capture_output=True,encoding='utf-8')
                        if result.returncode:raise RuntimeError('YouTube metadata retrieval failed')
                        received=True
                        value=json.loads(result.stdout);day=value.get('upload_date')
                        require(day and len(day)==8, 'YouTube publication date unavailable')
                        url=value.get('webpage_url',source['url'])
                        output.append(dict(item_id='youtube:'+value['id'],source_id=source['source_id'],
                            publisher_id=source['publisher_id'],kind=kind,title=value['title'],url=url,
                            published_at=f'{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00Z',retrieved_at=utc(),media_url=url,
                            discovery_method='youtube'))
                    else:
                        raw=fetch(source);received=True
                        output.extend(rss_records(source,raw,as_of))
                except Exception:
                    errors.append('Source retrieval failed: '+source['source_id'])
        code=1 if errors else 0
    except (Invalid,ValueError,KeyError,OSError):
        errors.append('Invalid or unavailable collector input/snapshot/fixture');code=2
    receipt(folder,'fetch_'+('feeds' if kind=='feed' else 'podcasts' if kind=='podcast' else 'youtube'),started,
        'success' if code==0 else 'partial' if output else 'failure',len(chosen) if 'chosen' in locals() else None,
        len(output),errors,dict(tool=tool,cost_usd=0 if tool.startswith('EXPLICIT') else None,
        network_requests_attempted=attempted,network_response_received=received,
        mode=run.get('mode') if 'run' in locals() else None))
    return output,code


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1] not in {'feed','podcast','youtube'}:
        raise SystemExit(2)
    folder=(ROOT/sys.argv[2]).resolve()
    require(folder.is_relative_to(ROOT) and (folder/'run.json').is_file(), 'Invalid collector run directory')
    records,code=collect(folder,sys.argv[1])
    for record in records:sys.stdout.buffer.write(canonical(record)+b'\n')
    raise SystemExit(code)
