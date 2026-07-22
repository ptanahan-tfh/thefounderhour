from __future__ import annotations
import html, json, re, shutil, unicodedata, urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'source'/'squarespace.xml'
DIST=ROOT/'dist'
RSS_URL='https://feeds.simplecast.com/C4Z8vbZb'
NS={'content':'http://purl.org/rss/1.0/modules/content/','wp':'http://wordpress.org/export/1.2/','dc':'http://purl.org/dc/elements/1.1/','itunes':'http://www.itunes.com/dtds/podcast-1.0.dtd'}


def text(el,path,default=''):
    v=el.findtext(path,default=default,namespaces=NS)
    return v or default

def slugify(s):
    s=unicodedata.normalize('NFKD',html.unescape(s)).encode('ascii','ignore').decode().lower()
    return re.sub(r'-+','-',re.sub(r'[^a-z0-9]+','-',s)).strip('-')

def norm_title(s):
    s=html.unescape(s).lower()
    s=re.sub(r'\b(ep(isode)?\.?\s*#?\d+|the founder hour|podcast)\b',' ',s)
    return re.sub(r'[^a-z0-9]+',' ',s).strip()

def strip_tags(s):
    s=re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>',' ',s,flags=re.I)
    s=re.sub(r'<[^>]+>',' ',s)
    return re.sub(r'\s+',' ',html.unescape(s)).strip()

def first_image(content):
    urls=re.findall(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)',content,re.I)
    for u in urls:
        if 'tfh_itunes' not in u.lower() and 'tfh_spotify' not in u.lower() and 'icon' not in u.lower():
            return html.unescape(u).replace('http://','https://')
    return ''

def clean_content(content):
    # Preserve meaningful prose and links, discard Squarespace layout wrappers and duplicate lead image.
    blocks=re.findall(r'<(?:p|h2|h3|blockquote|ul|ol)\b[^>]*>[\s\S]*?</(?:p|h2|h3|blockquote|ul|ol)>',content,re.I)
    out=[]
    for b in blocks:
        plain=strip_tags(b)
        if not plain or plain in {'⭐️⭐️⭐️⭐️⭐️'}: continue
        if len(plain)<3: continue
        b=re.sub(r'\s(?:class|style|data-[\w-]+)=("[^"]*"|\'[^\']*\')','',b,flags=re.I)
        b=re.sub(r'<a\s+','<a target="_blank" rel="noopener" ',b,flags=re.I)
        out.append(b)
    return '\n'.join(out) if out else f'<p>{html.escape(strip_tags(content))}</p>'

def parse_sqsp():
    root=ET.parse(SRC).getroot()
    episodes=[]
    for item in root.findall('./channel/item'):
        link=text(item,'link')
        if not link.startswith('/episodes/'): continue
        if text(item,'wp:status')!='publish': continue
        title=html.unescape(text(item,'title'))
        raw=text(item,'content:encoded')
        cats=[]; tags=[]
        for c in item.findall('category'):
            name=html.unescape(c.text or '').strip(); domain=c.get('domain','')
            if not name: continue
            (cats if domain=='category' else tags).append(name)
        date=text(item,'wp:post_date') or text(item,'pubDate')
        try: dt=datetime.fromisoformat(date.replace('Z','+00:00'))
        except Exception:
            try: dt=datetime.strptime(date[:19],'%Y-%m-%d %H:%M:%S')
            except Exception: dt=datetime(2000,1,1)
        episodes.append({'title':title,'slug':link.rstrip('/').split('/')[-1],'url':link,'date':dt,'year':str(dt.year),'image':first_image(raw),'body':clean_content(raw),'summary':strip_tags(raw)[:320],'categories':cats,'tags':tags})
    return sorted(episodes,key=lambda x:x['date'],reverse=True)

def fetch_rss():
    cache=ROOT/'source'/'simplecast.xml'
    data=None
    try:
        req=urllib.request.Request(RSS_URL,headers={'User-Agent':'Mozilla/5.0 TFH Archive Builder'})
        with urllib.request.urlopen(req,timeout=40) as r: data=r.read()
        cache.write_bytes(data)
        print(f'Fetched Simplecast RSS ({len(data)} bytes)')
    except Exception as e:
        print(f'Could not fetch live RSS: {e}')
        if cache.exists(): data=cache.read_bytes(); print('Using cached Simplecast RSS')
    if not data: return []
    root=ET.fromstring(data)
    out=[]
    for item in root.findall('./channel/item'):
        title=html.unescape(item.findtext('title') or '')
        guid=(item.findtext('guid') or '').strip()
        enclosure=item.find('enclosure'); audio=enclosure.get('url','') if enclosure is not None else ''
        link=item.findtext('link') or ''
        image=''
        im=item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}image')
        if im is not None: image=im.get('href','')
        pub=item.findtext('pubDate') or ''
        desc=item.findtext('description') or ''
        out.append({'title':title,'norm':norm_title(title),'guid':guid,'audio':audio,'link':link,'image':image,'pub':pub,'description':strip_tags(desc)})
    return out

def match_rss(episodes,rss):
    unused=set(range(len(rss)))
    for ep in episodes:
        target=norm_title(ep['title']); best=None; score=0
        for i in unused:
            cand=rss[i]['norm']; s=SequenceMatcher(None,target,cand).ratio()
            if target and (target in cand or cand in target): s=max(s,.9)
            if s>score: score,best=s,i
        if best is not None and score>=.58:
            ep['rss']=rss[best]; ep['match_score']=score; unused.remove(best)
            if not ep['image'] and rss[best]['image']: ep['image']=rss[best]['image']
        else: ep['rss']={}; ep['match_score']=0
    print(f'Matched {sum(bool(e["rss"]) for e in episodes)}/{len(episodes)} Squarespace episodes to RSS')
    return unused

def category(ep):
    if ep['categories']: return ep['categories'][0]
    t=(' '.join(ep['tags'])+' '+ep['title']).lower()
    mapping=[('Technology',['technology','software','app','saas','internet','ai','tech']),('Investing',['venture','investor','investment','capital','fund']),('Food & Hospitality',['food','restaurant','chef','beverage','hospitality']),('Consumer',['consumer','fashion','retail','beauty','brand']),('Media & Entertainment',['media','music','film','actor','entertainment','artist']),('Health & Wellness',['health','wellness','fitness','medical']),('Leadership',['leadership','operator','ceo'])]
    for c,keys in mapping:
        if any(k in t for k in keys): return c
    return 'Business'

def esc(s): return html.escape(str(s),quote=True)
def date_label(dt): return dt.strftime('%B %-d, %Y') if hasattr(dt,'strftime') else str(dt)
def head(title,desc,path):
    url='https://www.thefounderhour.com'+path
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><meta name="description" content="{esc(desc[:155])}"><link rel="canonical" href="{url}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc[:200])}"><meta property="og:type" content="website"><meta property="og:url" content="{url}"><link rel="stylesheet" href="/assets/styles.css"></head><body>'''
def header(active=''):
    return f'''<header class="masthead"><div class="wrap nav"><a class="brand" href="/"><img src="/assets/tfh-logo.png" alt="The Founder Hour"></a><nav class="navlinks"><a class="{'active' if active=='episodes' else ''}" href="/episodes/">Episodes</a><a class="{'active' if active=='about' else ''}" href="/about/">About</a></nav></div></header>'''
def footer():
    return '''<footer class="footer"><div class="wrap footer-grid"><div><img src="/assets/tfh-logo.png" alt="The Founder Hour"><p>Seven years of conversations. Preserved for future listeners.</p></div><div class="footer-links"><a href="/episodes/">Episodes</a><a href="/about/">About</a><a href="https://www.instagram.com/thefounderhour" target="_blank" rel="noopener">Instagram</a></div></div></footer></body></html>'''
def card(ep):
    return f'''<a class="card" href="/episodes/{esc(ep['slug'])}/"><div class="card-image">{f'<img src="{esc(ep["image"])}" alt="{esc(ep["title"])}" loading="lazy">' if ep['image'] else ''}</div><div class="meta">{esc(category(ep))} · {ep['year']}</div><h3>{esc(ep['title'])}</h3></a>'''

def write(path,content):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content,encoding='utf-8')

def build_home(eps):
    names=['Joe Gebbia','Ray Dalio','Max Levchin','Marc Lore','Jennifer Hyman','Keith Rabois']
    featured=[]
    for name in names:
        hit=next((e for e in eps if name.lower() in e['title'].lower()),None)
        if hit and hit not in featured: featured.append(hit)
    for e in eps:
        if len(featured)>=6: break
        if e not in featured and e['image']: featured.append(e)
    topics=sorted({category(e) for e in eps})
    body=head('The Founder Hour | Conversations with Remarkable Founders','Seven years of conversations with founders, investors, operators, and creators. Explore The Founder Hour collection.','/')+header()+f'''
<main><section class="hero"><div class="wrap"><p class="eyebrow">The complete collection · 2017–2024</p><h1>Conversations with people who built what came next.</h1><div class="hero-copy"><p>The Founder Hour explored the stories, decisions, setbacks, and ideas behind remarkable companies and creative careers—across more than {len(eps)} conversations.</p><a class="button" href="/episodes/">Explore all episodes</a></div></div></section>
<section class="section"><div class="wrap"><div class="section-head"><h2>Featured conversations</h2><p>A selection from seven years of candid discussions with founders, investors, operators, and creators.</p></div><div class="featured">{''.join(card(e) for e in featured[:5])}</div></div></section>
<section class="section"><div class="wrap"><div class="section-head"><h2>Explore by subject</h2><p>Search the full collection or begin with a field that interests you.</p></div><div class="topics">{''.join(f'<a class="topic" href="/episodes/?topic={esc(t)}">{esc(t)}</a>' for t in topics)}</div></div></section>
<section class="section legacy"><div class="wrap legacy-grid"><div><p class="eyebrow">About the show</p><h2>Seven years of stories, ideas, and hard-earned perspective.</h2><p>Hosted and produced from 2017 through 2024, The Founder Hour became a top-ranked business podcast by focusing on the people behind the companies—not just the headlines.</p><a class="button" href="/about/">Read the story</a></div><div class="stats"><div class="stat"><strong>{len(eps)}+</strong><span>Conversations</span></div><div class="stat"><strong>7</strong><span>Years</span></div><div class="stat"><strong>Top 1%</strong><span>Global podcast</span></div></div></div></section></main>'''+footer()
    write(DIST/'index.html',body)

def build_archive(eps):
    cats=sorted({category(e) for e in eps})
    rows=[]
    for e in eps:
        cat=category(e); search=(e['title']+' '+cat+' '+' '.join(e['tags'])).lower()
        rows.append(f'''<a class="episode-row" href="/episodes/{esc(e['slug'])}/" data-search="{esc(search)}" data-category="{esc(cat)}">{f'<img src="{esc(e["image"])}" alt="" loading="lazy">' if e['image'] else '<div></div>'}<div><div class="meta">{esc(cat)} · {e['year']}</div><h2>{esc(e['title'])}</h2></div><span class="arrow">→</span></a>''')
    body=head('Episodes | The Founder Hour','Browse and search the complete collection of Founder Hour conversations.','/episodes/')+header('episodes')+f'''<main><section class="archive-hero"><div class="wrap"><p class="eyebrow">2017–2024</p><h1>All conversations</h1><div class="searchbar"><input id="episode-search" type="search" placeholder="Search guests, companies, topics…" aria-label="Search episodes"><span class="button dark" id="result-count">{len(eps)} conversations</span></div></div></section><div class="wrap archive-layout"><aside class="filters"><h3>Browse by subject</h3><button class="filter-btn active" data-filter="all">All subjects</button>{''.join(f'<button class="filter-btn" data-filter="{esc(c)}">{esc(c)}</button>' for c in cats)}</aside><section class="episode-list">{''.join(rows)}</section></div></main><script src="/assets/site.js"></script>'''+footer()
    write(DIST/'episodes'/'index.html',body)

def build_episode(ep):
    rss=ep.get('rss',{}); guid=rss.get('guid',''); audio=rss.get('audio','')
    player=''
    if guid and re.fullmatch(r'[0-9a-fA-F-]{20,}',guid):
        player=f'<iframe height="200" src="https://player.simplecast.com/{esc(guid)}?dark=false" title="Simplecast audio player" loading="lazy"></iframe>'
    elif audio:
        player=f'<audio controls preload="none" src="{esc(audio)}">Your browser does not support audio playback.</audio>'
    elif rss.get('link'):
        player=f'<a class="button dark" href="{esc(rss["link"])}" target="_blank" rel="noopener">Listen on Simplecast</a>'
    else:
        player='<p>Audio player unavailable in this preview. The build will connect it from the Simplecast RSS feed.</p>'
    desc=ep['summary'] or rss.get('description','') or ep['title']
    body=head(f'{ep["title"]} | The Founder Hour',desc,f'/episodes/{ep["slug"]}/')+header('episodes')+f'''<main class="episode-page"><div class="wrap"><div class="episode-header"><div class="episode-cover">{f'<img src="{esc(ep["image"])}" alt="{esc(ep["title"])}">' if ep['image'] else ''}</div><div class="episode-title"><p class="eyebrow">{esc(category(ep))}</p><h1>{esc(ep['title'])}</h1><p class="date">{esc(date_label(ep['date']))}</p><div class="player">{player}</div></div></div><div class="article-grid section"><aside class="article-label">About this episode</aside><article class="article-body">{ep['body']}</article></div></div></main>'''+footer()
    write(DIST/'episodes'/ep['slug']/'index.html',body)

def build_about(count):
    body=head('About | The Founder Hour','The story of The Founder Hour, a seven-year podcast featuring founders, investors, operators, and creators.','/about/')+header('about')+f'''<main><section class="hero"><div class="wrap"><p class="eyebrow">The Founder Hour · 2017–2024</p><h1>A long-form record of how remarkable people built their lives and work.</h1></div></section><section class="section"><div class="wrap article-grid"><aside class="article-label">About the show</aside><article class="article-body"><p>The Founder Hour was created to move beyond polished success stories and understand the experiences that shaped founders, investors, operators, and creators.</p><p>Across seven years and more than {count} conversations, the show explored beginnings, ambition, risk, failure, reinvention, leadership, and the personal realities behind building something meaningful.</p><p>The podcast concluded in 2024. This site preserves the complete collection for listeners discovering these conversations for the first time and for those returning to them years later.</p></article></div></section></main>'''+footer()
    write(DIST/'about'/'index.html',body)

def build_sitemap(eps):
    urls=['/','/about/','/episodes/']+[f'/episodes/{e["slug"]}/' for e in eps]
    xml='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>https://www.thefounderhour.com{u}</loc></url>' for u in urls)+'</urlset>'
    write(DIST/'sitemap.xml',xml); write(DIST/'robots.txt','User-agent: *\nAllow: /\nSitemap: https://www.thefounderhour.com/sitemap.xml\n')

def main():
    if DIST.exists(): shutil.rmtree(DIST)
    DIST.mkdir(); shutil.copytree(ROOT/'assets',DIST/'assets')
    eps=parse_sqsp(); rss=fetch_rss(); unused=match_rss(eps,rss)
    # Add any RSS-only episodes so the podcast feed remains the complete source of truth.
    for i in sorted(unused):
        r=rss[i]
        try:
            from email.utils import parsedate_to_datetime
            dt=parsedate_to_datetime(r.get('pub',''))
        except Exception:
            dt=datetime(2000,1,1)
        link=r.get('link','')
        candidate=link.rstrip('/').split('/')[-1] if link else slugify(r['title'])
        slug=candidate if candidate and candidate not in {'episodes',''} else slugify(r['title'])
        body=f"<p>{html.escape(r.get('description',''))}</p>" if r.get('description') else '<p>Listen to this episode of The Founder Hour.</p>'
        eps.append({'title':r['title'],'slug':slug,'url':'/episodes/'+slug,'date':dt,'year':str(dt.year),'image':r.get('image',''),'body':body,'summary':r.get('description','')[:320],'categories':[],'tags':[],'rss':r,'match_score':1})
    # Normalize every date to timezone-aware UTC before sorting.
    # Squarespace exports naive datetimes; Simplecast RSS dates include offsets.
    def utc_date(episode):
        dt = episode.get('date')
        if not isinstance(dt, datetime):
            return datetime(2000, 1, 1, tzinfo=timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    for episode in eps:
        episode['date'] = utc_date(episode)

    eps=sorted(eps,key=lambda x:x['date'],reverse=True)
    for e in eps: build_episode(e)
    build_home(eps); build_archive(eps); build_about(len(eps)); build_sitemap(eps)
    (DIST/'_redirects').write_text('/episodes/:slug /episodes/:slug/ 301\n',encoding='utf-8')
    report={'squarespace_episodes':len(eps),'rss_items':len(rss),'matched':sum(bool(e.get('rss')) for e in eps),'unmatched':[e['title'] for e in eps if not e.get('rss')]}
    write(ROOT/'migration-report.json',json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps({k:v for k,v in report.items() if k!='unmatched'},indent=2))

if __name__=='__main__': main()
