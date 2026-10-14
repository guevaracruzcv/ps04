"""Normal-run extraction/reuse; no paid transcription boundary is invoked."""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from pipeline_common import ROOT, Invalid, canonical, digest, jsonl, load, policy, receipt, relative, require, utc, write_new
from processing.evidence_contract import finalize, fixture, check_media
from processing.extract_content import extract_article_body


def cached_items(folder):
    records=jsonl(folder/'config/evidence_cache.jsonl')
    if (folder/'prior_corpus.jsonl').exists():
        records += jsonl(folder/'prior_corpus.jsonl')
    return records


def legacy_match(candidate, cache):
    for old in reversed(cache):
        identity=old['media_url']==candidate.get('media_url') if candidate['kind']=='podcast' else old['url']==candidate['url']
        if old['kind']==candidate['kind'] and identity:
            # Source IDs can be aliases; originating publisher and source content cannot.
            return old
    return None


def metadata_matches(candidate, old):
    if candidate['kind']=='podcast':
        from datetime import datetime, timezone
        def day(value):return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc).date()
        def title(value):return ' '.join(value.casefold().split())
        return (bool(candidate.get('published_at')) and candidate.get('media_url')==old['media_url'] and candidate.get('publisher_id')==old['publisher_id'] and
                title(candidate['title'])==title(old['title']) and day(candidate['published_at'])==day(old['published_at']))
    return all(candidate.get(k)==old.get(k) for k in ['title','publisher_id','published_at','url','media_url'])


def source_media(folder,candidate,mock):
    base=ROOT/'data/media/contract_v2'/folder.name/digest(candidate['item_id'].encode())[:20]
    if mock is not None:
        data=(ROOT/mock['media_path']).read_bytes()
        require(bool(data), 'Missing offline media fixture')
        path=base/(digest(candidate['item_id'].encode())[:20]+'.offline-media')
        write_new(path,data)
        return dict(source_media_path=relative(path),source_media_sha256=digest(data),media_is_fixture=True)
    require(os.environ.get('PS04_ALLOW_COLLECTION')=='1','Original source media retrieval requires authorization')
    base.mkdir(parents=True,exist_ok=False)
    pattern=str(base/(candidate['item_id'].split(':',1)[1]+'.%(ext)s'))
    subprocess.run([sys.executable,'-m','yt_dlp','--js-runtimes','node','--no-playlist',
        '-f','bestaudio','-o',pattern,candidate['url']],check=True,stdout=sys.stderr)
    found=[p for p in base.glob('*') if p.is_file() and p.suffix not in {'.part','.ytdl'}]
    require(len(found)==1 and found[0].stat().st_size>0,'Original YouTube audio unavailable')
    return dict(source_media_path=relative(found[0]),source_media_sha256=digest(found[0].read_bytes()),media_is_fixture=False)


def extract_one(folder,candidate,cache,mocks):
    if candidate['kind']=='youtube' and mocks is None:
        # A related but invalid archive must fail, not fall through to retrieval.
        archived=next((x for x in reversed(cache) if
            x.get('item_id')==candidate.get('item_id') or x.get('url')==candidate.get('url') or
            (candidate.get('media_url') is not None and x.get('media_url')==candidate['media_url'])),None)
        if archived is not None:
            keys=['item_id','source_id','publisher_id','title','url','published_at','media_url']
            require(archived.get('kind')=='youtube' and all(isinstance(candidate.get(k),str) and
                    bool(candidate[k]) and candidate[k]==archived.get(k) for k in keys),
                    'Archived YouTube identity/metadata mismatch')
            require(candidate['item_id'].startswith('youtube:'), 'Archived YouTube video ID mismatch')
            video_id=candidate['item_id'].split(':',1)[1]
            for key in ['url','media_url']:
                parsed=urlparse(candidate[key])
                require(bool(video_id) and parsed.hostname in {'youtube.com','www.youtube.com','m.youtube.com'} and
                        parsed.path=='/watch' and parse_qs(parsed.query).get('v')==[video_id],
                        'Archived YouTube video ID mismatch')
            require(candidate.get('version_id',archived.get('version_id'))==archived.get('version_id'),
                    'Archived YouTube evidence version mismatch')
            require(archived.get('media_is_fixture') is False, 'Archived YouTube fixtures or unbound media forbidden')
            require(all(isinstance(archived.get(k),str) and bool(archived[k]) for k in
                        ['version_id','text_sha256','segments_sha256','source_media_sha256']),
                    'Archived YouTube evidence hashes missing')
            paths={}
            for key in ['text_path','segments_path','source_media_path']:
                require(isinstance(archived.get(key),str) and bool(archived[key]),
                        'Archived YouTube asset binding missing: '+key)
                # Reject outside/UNC paths lexically before filesystem resolution.
                path=Path(os.path.abspath(ROOT/archived[key]))
                bases=[ROOT/'data/media/contract_v2'] if key=='source_media_path' else [ROOT/'data/assets',ROOT/'runs']
                require(path.is_relative_to(ROOT) and any(path.is_relative_to(base) for base in bases),
                        'Archived YouTube asset escapes project evidence area: '+key)
                paths[key]=path
            for key,path in paths.items():
                require(not any(p.is_symlink() or p.is_junction() for p in [path,*path.parents]
                                if p.is_relative_to(ROOT)), 'Archived YouTube linked asset forbidden: '+key)
                resolved=path.resolve()
                bases=[ROOT/'data/media/contract_v2'] if key=='source_media_path' else [ROOT/'data/assets',ROOT/'runs']
                require(resolved.is_relative_to(ROOT) and any(resolved.is_relative_to(base) for base in bases),
                        'Archived YouTube asset escapes project evidence area: '+key)
                paths[key]=resolved
            from pipeline_common import validate_items
            validate_items([archived],folder)
            text=paths['text_path'].read_bytes()
            require(digest(text)==archived['text_sha256'], 'Archived YouTube text hash mismatch')
            segments=load(paths['segments_path'])
            require('\n'.join(x['text'] for x in segments)==text.decode('utf-8'),
                    'Archived YouTube transcript/segments mismatch')
            return dict(archived,reuse_method='verified immutable archived YouTube bundle; no caption or media download',
                        reused_at_utc=utc())
    old=legacy_match(candidate,cache)
    value=dict(candidate)
    if old:
        value['item_id']=old['item_id']
        value['source_id']=old['source_id']
    mock=mocks.get(candidate['url']) if mocks is not None else None
    if candidate.get('reuse_cached_evidence'):
        require(old is not None and metadata_matches(candidate,old),'Cached source identity/metadata mismatch')
        data=(ROOT/old['text_path']).read_bytes()
        from processing.evidence_contract import verify_version
        verify_version(old,data)
        from workflows.editorial_run import discovery_annotations
        route=discovery_annotations([old])[0]
        result=dict(old,text_path=relative(ROOT/old['text_path']),segments_path=relative(ROOT/old['segments_path']) if old.get('segments_path') else None,
            discovery_method=route['discovery_method'],discovery_provenance=route['discovery_provenance'],
            reuse_method='date-eligible immutable archived version; not a fresh page download',reused_at_utc=utc())
        return result
    if candidate['kind']=='podcast':
        require(old is not None and metadata_matches(candidate,old),'Podcast identity/enclosure/date unavailable; no paid transcription performed')
        audio_name='imf_innovation_blindspot.mp3' if old['publisher_id']=='imf' else 'reuters_ai_at_work.mp3'
        audio=ROOT/'runs/test-podcasts/audio'/audio_name
        require(audio.is_file() and audio.stat().st_size>0,'Archived podcast audio unavailable')
        value.update(old,retrieved_at=old['retrieved_at'],discovery_method='podcast_rss',reused_at_utc=utc(),
            fresh_rss_candidate=candidate,source_media_path=relative(audio),source_media_sha256=digest(audio.read_bytes()),media_is_fixture=False)
        text=(ROOT/old['text_path']).read_bytes();segments=(ROOT/old['segments_path']).read_bytes()
    elif candidate['kind']=='youtube':
        if mocks is not None:
            require(mock is not None,'YouTube offline extraction fixture missing')
            text=(ROOT/mock['text_path']).read_bytes();segments=(ROOT/mock['segments_path']).read_bytes()
        else:
            from processing.extract_youtube import extract_youtube
            require(os.environ.get('PS04_ALLOW_COLLECTION')=='1','Caption retrieval requires authorization')
            extracted=extract_youtube(candidate,folder)
            text=(ROOT/extracted['text_path']).read_bytes();segments=(ROOT/extracted['segments_path']).read_bytes()
        value.update(source_media(folder,candidate,mock),discovery_method='youtube')
    else:
        require(candidate['url'].startswith('https://news.mit.edu/'),'Only existing MIT extractor is used for fresh written sources')
        if mocks is not None:
            require(mock is not None,'Written extraction fixture missing')
            text=(ROOT/mock['text_path']).read_bytes()
        else:
            require(os.environ.get('PS04_ALLOW_COLLECTION')=='1','Web extraction requires authorization')
            with urllib.request.urlopen(urllib.request.Request(candidate['url'],headers={'User-Agent':'PS04 Research'}),timeout=30) as response:
                text=extract_article_body(response.read().decode(response.headers.get_content_charset() or 'utf-8',errors='replace')).encode('utf-8')
        segments=None;value['discovery_method']='rss'
    if old and metadata_matches(candidate,old):
        value.update({k:old[k] for k in ['item_id','source_id','publisher_id','title','url','published_at','media_url']})
    result=finalize(value,text,segments,folder,old)
    if result['kind']!='feed':check_media(result)
    return result


def extract(folder,candidates):
    started=utc();items=[];errors=[];matched=0;unprocessed=[]
    try:
        policy(folder);cache=cached_items(folder);mocks=fixture(folder,'extractions.json')
        seen=set()
        for candidate in candidates:
            try:
                key=(candidate['kind'],candidate.get('media_url') if candidate['kind']=='podcast' else candidate['url'])
                if key in seen:continue
                seen.add(key)
                if candidate['kind']=='podcast':
                    old=legacy_match(candidate,cache)
                    if old is None or not metadata_matches(candidate,old):
                        unprocessed.append(dict(item_id=candidate['item_id'],version_id=None,url=candidate['url'],
                            reason='no_verified_archive_match_no_authorized_transcription',transcription_performed=False))
                        continue
                item=extract_one(folder,candidate,cache,mocks);items.append(item)
                if item['kind']=='podcast':matched+=1
            except Exception as exc:
                errors.append(dict(item_id=candidate.get('item_id'),error=str(exc) if isinstance(exc,Invalid) else 'Source extraction failed'))
        if matched<2:errors.append(dict(item_id=None,error='Fewer than two verified podcast audio/transcript matches; no transcription performed'))
    except (Invalid,ValueError,OSError,KeyError) as exc:
        errors.append(dict(item_id=None,error=str(exc)))
    write_new(folder/'processing_exclusions.jsonl',b''.join(canonical(x)+b'\n' for x in unprocessed))
    receipt(folder,'extract_content',started,'partial' if errors and items else 'failure' if errors else 'success',
        len(candidates),len(items),errors,dict(cost_usd=0 if load(folder/'run.json')['mode']=='contract_offline_test' else None,
        tool='EXPLICIT OFFLINE EXTRACTION FIXTURE' if load(folder/'run.json')['mode']=='contract_offline_test' else 'Existing extraction/cache/yt_dlp',
        transcription_performed=False,unprocessed_podcast_candidates=len(unprocessed)))
    return items,1 if errors else 0


if __name__=='__main__':
    from pipeline_common import run_folder, parse_lines
    if len(sys.argv)!=2:raise SystemExit(2)
    folder=run_folder(sys.argv[1])
    try:
        candidates=parse_lines(sys.stdin.buffer.read().decode('utf-8'))
    except (Invalid, UnicodeError):
        receipt(folder,'extract_content',utc(),'failure',None,0,['Malformed extraction JSONL'],dict(cost_usd=0))
        raise SystemExit(2)
    items,code=extract(folder,candidates)
    for item in items:sys.stdout.buffer.write(canonical(item)+b'\n')
    raise SystemExit(code)
