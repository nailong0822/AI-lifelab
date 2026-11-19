/** Scalable local worlds, with broad terrain and a shared upper-left light. */
const palettes = [
  ['#dbe4ed', '#889eaf', '#344c64', '#b6d0df'],
  ['#ffe1ae', '#cf9472', '#68465c', '#edbe91'],
  ['#c4f1dd', '#4caaa8', '#184b68', '#94ddd5'],
  ['#e1d5fa', '#9c8cc9', '#443f75', '#c8c0f1'],
  ['#d5ecff', '#7dadd0', '#304f86', '#b4dafa'],
]

function world(index: number) {
  const [light, mid, dark, rim] = palettes[index]
  const terrain = [
    `<g fill="#607c94" opacity=".3"><circle cx="107" cy="109" r="23"/><circle cx="188" cy="186" r="35"/><circle cx="104" cy="218" r="13"/><circle cx="211" cy="86" r="12"/></g><g fill="none" stroke="#eef5fa" stroke-opacity=".35" stroke-width="3"><path d="M85 108a23 23 0 0 1 43-8M155 185a35 35 0 0 1 65-13M93 218a13 13 0 0 1 23-7"/></g><path d="M30 149Q99 127 159 150T293 157M39 167Q99 145 145 165" fill="none" stroke="#d9e7f0" stroke-opacity=".16" stroke-width="5"/>`,
    `<g fill="none" stroke-linecap="round"><path d="M21 127Q79 81 160 117T306 132M12 175Q89 115 177 164T305 173M39 215Q110 160 185 208T304 215" stroke="#f7cc98" stroke-width="20" opacity=".45"/><path d="M31 137Q97 93 165 129T305 143M34 187Q110 139 187 184T299 184" stroke="#965e63" stroke-width="5" opacity=".38"/></g>`,
    `<path d="M51 57L95 44 128 62 124 88 151 101 147 126 125 137 124 159 101 177 104 203 85 213 65 186 66 158 45 148 33 114Z" fill="#88bfa0"/><path d="M184 92L217 77 249 95 251 118 277 133 279 163 255 175 241 199 217 204 202 235 177 223 185 197 167 174 178 153 161 133Z" fill="#a4ccb0"/><path d="M55 65L93 53 115 65M181 103L215 88 243 101M178 174L197 191 192 215" fill="none" stroke="#d7e8b5" stroke-width="6" opacity=".45"/><g fill="none" stroke="#f4ffff" stroke-linecap="round" opacity=".45"><path d="M54 93Q104 68 169 86M123 223Q192 242 249 207" stroke-width="9"/><path d="M132 70Q185 63 221 74M56 193Q90 181 130 188" stroke-width="4"/></g>`,
    `<g fill="none" stroke-linecap="round"><path d="M18 104Q114 130 305 92M13 145Q142 185 309 134M25 201Q147 233 303 187" stroke="#dfc1e9" stroke-width="22" opacity=".45"/><path d="M17 121Q160 153 311 107M20 171Q172 210 309 157M35 220Q181 249 302 204" stroke="#716aa6" stroke-width="7" opacity=".5"/></g><ellipse cx="193" cy="175" rx="30" ry="12" fill="#f1d5e8" opacity=".5" transform="rotate(-7 193 175)"/>`,
    `<path d="M34 103L91 48 133 41 157 62 183 47 222 60 201 88 214 110 177 124 162 158 134 150 106 174 83 147 61 150Z" fill="#dfedf1" opacity=".8"/><path d="M210 173L246 153 278 167 282 209 251 242 208 248 191 222Z" fill="#c7e2ec" opacity=".75"/><path d="M56 103L91 74 127 65 142 81 129 107 149 119 131 141M212 193L241 181 259 196 241 223" fill="none" stroke="#8bbacb" stroke-width="4" opacity=".7"/><g fill="none" stroke="#f2faff" opacity=".4"><path d="M44 196Q128 163 181 194M130 96Q219 125 277 96" stroke-width="8"/><path d="M65 221Q116 202 151 215" stroke-width="3"/></g>`,
  ][index]
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 320"><defs>
    <radialGradient id="base" cx="28%" cy="23%" r="90%"><stop stop-color="${light}"/><stop offset=".42" stop-color="${mid}"/><stop offset="1" stop-color="${dark}"/></radialGradient>
    <radialGradient id="shade" cx="25%" cy="22%" r="85%"><stop offset=".34" stop-color="#06152c" stop-opacity="0"/><stop offset=".76" stop-color="#07142b" stop-opacity=".15"/><stop offset="1" stop-color="#061327" stop-opacity=".83"/></radialGradient>
    <radialGradient id="shine" cx="27%" cy="20%" r="74%"><stop stop-color="#fff" stop-opacity=".24"/><stop offset=".6" stop-color="#fff" stop-opacity="0"/></radialGradient>
    <linearGradient id="rim" x2="1" y2="1"><stop stop-color="${rim}" stop-opacity=".9"/><stop offset=".5" stop-color="${rim}" stop-opacity=".1"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
    <linearGradient id="ring"><stop stop-color="#ab9bbf" stop-opacity=".15"/><stop offset=".45" stop-color="#e6cee6" stop-opacity=".85"/><stop offset="1" stop-color="#9b8ebc" stop-opacity=".3"/></linearGradient>
    <clipPath id="sphere"><circle cx="160" cy="160" r="123"/></clipPath>
  </defs>
  ${index === 3 ? '<ellipse cx="160" cy="160" rx="157" ry="47" transform="rotate(-27 160 160)" fill="none" stroke="url(#ring)" stroke-width="11"/>' : ''}
  <circle cx="160" cy="160" r="126" fill="${rim}" opacity=".09"/><circle cx="160" cy="160" r="123" fill="url(#base)"/>
  <g clip-path="url(#sphere)">${terrain}<circle cx="160" cy="160" r="124" fill="url(#shade)"/><circle cx="160" cy="160" r="124" fill="url(#shine)"/></g>
  <circle cx="160" cy="160" r="123" fill="none" stroke="url(#rim)" stroke-width="2"/>
  ${index === 3 ? '<path d="M20 210C38 232 117 221 187 185S298 120 300 107" fill="none" stroke="url(#ring)" stroke-width="10"/><path d="M20 216C58 238 158 202 218 165S295 116 300 111" fill="none" stroke="#e7d7ed" stroke-opacity=".25" stroke-width="2"/>' : ''}
  </svg>`
}
const cache = new Map<number, string>()
export function planetImage(index: number) {
  const kind = ((index % 5) + 5) % 5
  if (!cache.has(kind)) cache.set(kind, 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(world(kind)))
  return cache.get(kind)!
}
