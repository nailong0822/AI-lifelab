/** Shared art direction for WebGL planets and their lightweight SVG fallback. */
export const planetThemes = [
  {core:'#092c4a',light:'#48f5e4',accent:'#85b8ff'},
  {core:'#20143e',light:'#bc8cff',accent:'#ff8de8'},
  {core:'#102b48',light:'#8ce9ff',accent:'#d6efff'},
  {core:'#352037',light:'#ffb66b',accent:'#ff6f9b'},
  {core:'#0a3437',light:'#72ffd1',accent:'#9ed4ff'},
  {core:'#252052',light:'#8fafff',accent:'#f0b0ff'},
]
export const planetTheme=(index:number)=>planetThemes[((index%planetThemes.length)+planetThemes.length)%planetThemes.length]
const cache=new Map<number,string>()
export function techPlanetImage(index:number) {
  const key=((index%planetThemes.length)+planetThemes.length)%planetThemes.length
  if(cache.has(key))return cache.get(key)!
  const theme=planetTheme(key)
  const dots=Array.from({length:44},(_,i)=>{
    const angle=i*2.399,rad=132+(i*17%44),x=200+Math.cos(angle)*rad,y=200+Math.sin(angle)*rad*.64
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${i%5===0?2.3:1}" fill="${i%3?theme.light:theme.accent}" opacity="${.35+(i%5)*.12}"/>`
  }).join('')
  const grid=Array.from({length:9},(_,i)=>`<ellipse cx="200" cy="200" rx="${16+i*13}" ry="110"/><ellipse cx="200" cy="${112+i*22}" rx="${Math.sqrt(Math.max(0,12100-Math.pow(88-i*22,2)))}" ry="6"/>`).join('')
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><defs>
    <radialGradient id="halo"><stop offset=".42" stop-color="${theme.light}" stop-opacity=".1"/><stop offset=".56" stop-color="${theme.light}" stop-opacity=".25"/><stop offset="1" stop-color="${theme.light}" stop-opacity="0"/></radialGradient>
    <radialGradient id="shell" cx="30%" cy="25%" r="80%"><stop stop-color="${theme.light}" stop-opacity=".55"/><stop offset=".35" stop-color="${theme.core}"/><stop offset=".8" stop-color="#070e24"/><stop offset="1" stop-color="${theme.light}" stop-opacity=".75"/></radialGradient>
    <radialGradient id="rim"><stop offset=".7" stop-color="${theme.light}" stop-opacity="0"/><stop offset="1" stop-color="${theme.light}" stop-opacity=".7"/></radialGradient>
    <clipPath id="body"><circle cx="200" cy="200" r="110"/></clipPath>
    <filter id="glow"><feGaussianBlur stdDeviation="2.6"/></filter>
  </defs><circle cx="200" cy="200" r="188" fill="url(#halo)"/>
  <ellipse cx="200" cy="200" rx="171" ry="49" fill="none" stroke="${theme.light}" stroke-opacity=".22" stroke-width="6" transform="rotate(-24 200 200)"/>
  <circle cx="200" cy="200" r="110" fill="url(#shell)"/>
  <g clip-path="url(#body)" fill="none" stroke="${theme.light}" stroke-opacity=".2" stroke-width=".65" transform="rotate(-15 200 200)">${grid}</g>
  <g clip-path="url(#body)"><path d="M94 175L132 161 151 173 173 147 201 152 222 129 249 145 267 125M107 232L136 219 164 228 188 208 218 222 247 201 290 214M153 100L169 143 156 177 178 211 166 250 193 305" fill="none" stroke="${theme.light}" stroke-width="2.5" filter="url(#glow)"/><path d="M94 175L132 161 151 173 173 147 201 152 222 129 249 145 267 125M107 232L136 219 164 228 188 208 218 222 247 201 290 214" fill="none" stroke="${theme.light}" stroke-width="1.2"/><path d="M97 190Q202 173 307 190" fill="none" stroke="${theme.accent}" stroke-width="3" opacity=".8"/></g>
  <circle cx="200" cy="200" r="110" fill="url(#rim)"/><circle cx="200" cy="200" r="112" fill="none" stroke="${theme.light}" stroke-width="1.3" opacity=".75"/>
  <ellipse cx="200" cy="200" rx="171" ry="49" fill="none" stroke="${theme.light}" stroke-width="1.5" stroke-dasharray="80 16 4 15" transform="rotate(-24 200 200)"/>
  <ellipse cx="200" cy="200" rx="150" ry="88" fill="none" stroke="${theme.accent}" stroke-width=".8" stroke-dasharray="3 12" transform="rotate(48 200 200)"/>${dots}</svg>`
  const result='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg)
  cache.set(key,result)
  return result
}
