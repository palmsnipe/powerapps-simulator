"""Bundle Microsoft's pinned Fluent SVG package. Build-time network only; no npm."""
from pathlib import Path
import base64,hashlib,io,json,re,tarfile,urllib.request
import xml.etree.ElementTree as ET

VERSION='1.1.344'
URL=f'https://registry.npmjs.org/@fluentui/svg-icons/-/svg-icons-{VERSION}.tgz'
INTEGRITY='rasjaq4hBXzRS25pSY9gaqwY7NdvZJCz7G/rtpwF6mCmg2R+9TnySLhHbR+sOpkMP/IDDG28XvxRcNEQ/lJYoQ=='
ROOT=Path(__file__).resolve().parents[1]/'powerapps_sim/static'
SVG='http://www.w3.org/2000/svg'
ET.register_namespace('',SVG)

def main():
    data=urllib.request.urlopen(URL).read()
    if base64.b64encode(hashlib.sha512(data).digest()).decode()!=INTEGRITY:raise ValueError('Pinned icon package integrity mismatch')
    selected={};license_text=notice_text=None
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
        for member in archive.getmembers():
            if not member.isfile():continue
            if member.name in ('package/LICENSE','package/LICENSE.md'):license_text=archive.extractfile(member).read().decode()
            if member.name=='package/NOTICE':notice_text=archive.extractfile(member).read().decode()
            match=re.fullmatch(r'package/icons/(?:ic_fluent_)?([a-z0-9_]+)_(\d+)_(regular|filled)\.svg',member.name)
            if not match:continue
            raw,size,style=match.groups();size=int(size)
            name=''.join(part[:1].upper()+part[1:] for part in raw.split('_'))
            key=(name,style);priority=(abs(size-24),-size)
            if key not in selected or priority<selected[key][0]:
                selected[key]=(priority,member.name,archive.extractfile(member).read())
    # The SVG npm tarball omits notices; retain those from its exact gitHead.
    upstream='https://raw.githubusercontent.com/microsoft/fluentui-system-icons/f1260014e8a4fcfa6777182fd6cf082fc5e952d8/'
    notices={}
    for name,digest in [('LICENSE','69bc45dc42b9acb96a69823adbc6ae538374e3c0bde169b855b32c48eaaef52f'),('NOTICE','2fb367a84df52c8b6f8401119708014b327f595554d41712d7407151c9ce73ef')]:
        raw=urllib.request.urlopen(upstream+name).read()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Pinned notice integrity mismatch')
        notices[name]=raw.decode()
    license_text,notice_text=notices['LICENSE'],notices['NOTICE']
    sprite=ET.Element(f'{{{SVG}}}svg');icons={};chosen={}
    allowed={'svg','g','path','circle','rect','line','polyline','polygon','ellipse','defs','clipPath'}
    for (name,style),(_,source,raw) in sorted(selected.items()):
        tree=ET.fromstring(raw);ident=name+'-'+style
        for element in tree.iter():
            tag=element.tag.split('}')[-1]
            if tag not in allowed or any(k.startswith('on') or k.endswith('href') for k in element.attrib):raise ValueError('Unexpected active SVG content')
            for key,value in list(element.attrib.items()):
                if key=='id':element.set(key,ident+'__'+value)
                elif 'url(#' in value:element.set(key,re.sub(r'url\(#([^)]+)\)',lambda m:'url(#'+ident+'__'+m[1]+')',value))
        viewbox=tree.get('viewBox') or f"0 0 {tree.get('width')} {tree.get('height')}"
        symbol=ET.SubElement(sprite,f'{{{SVG}}}symbol',{'id':ident,'viewBox':viewbox})
        symbol.extend(list(tree));icons.setdefault(name,{})['Outline' if style=='regular' else 'Filled']=ident
        chosen[ident]=source
    (ROOT/'fluent-icons.svg').write_text(ET.tostring(sprite,encoding='unicode')+'\n')
    (ROOT/'fluent-icons.json').write_text(json.dumps({'package':'@fluentui/svg-icons','version':VERSION,'source':URL,'sha512':INTEGRITY,'icons':icons,'assets':chosen},sort_keys=True,separators=(',',':'))+'\n')
    (ROOT/'fluent-icons-LICENSE.txt').write_text(license_text)
    (ROOT/'fluent-icons-NOTICE.txt').write_text(notice_text or 'Microsoft Fluent UI System Icons\nSource: https://github.com/microsoft/fluentui-system-icons\nSVG package: @fluentui/svg-icons '+VERSION+'\nSee fluent-icons-LICENSE.txt for the MIT license.\n')
    print(f'Bundled {len(icons)} names / {len(selected)} glyphs from Microsoft Fluent {VERSION}')

if __name__=='__main__':main()
