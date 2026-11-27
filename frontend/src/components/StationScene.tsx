import { useEffect, useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'

type SceneProps = {light: boolean; animate: boolean; focused: boolean; sending: boolean; onReady: () => void; onFailure: () => void}
const windowPoints: [number, number][] = [[-8,-1.7],[-7,-2.6],[7,-2.6],[8,-1.7],[8,4.1],[7,5],[-7,5],[-8,4.1]]

function polygon(points: [number, number][]) {
  const path = new THREE.Shape()
  path.moveTo(...points[0]); points.slice(1).forEach(point => path.lineTo(...point)); path.closePath()
  return path
}

function Frame({scale, color, depth = .25, bevel = .08, metallic = true}: {scale: number; color: string; depth?: number; bevel?: number; metallic?: boolean}) {
  const geometry = useMemo(() => {
    const outer = polygon(windowPoints.map(([x,y]) => [x*scale,y*scale]))
    const inner = polygon(windowPoints)
    outer.holes.push(new THREE.Path(inner.getPoints().reverse()))
    return new THREE.ExtrudeGeometry(outer, {depth, bevelEnabled: true, bevelThickness:bevel, bevelSize:bevel, bevelSegments:2, steps:1, curveSegments:1})
  }, [scale,depth,bevel])
  useEffect(() => () => geometry.dispose(), [geometry])
  return <mesh geometry={geometry}>
    {metallic ? <meshStandardMaterial color={color} metalness={.78} roughness={.3}/> : <meshBasicMaterial color={color} toneMapped={false}/>}
  </mesh>
}

function Beam({position, size, color, glow = false, rotation, opacity = 1}: {position: [number,number,number]; size: [number,number,number]; color: string; glow?: boolean; rotation?: [number,number,number]; opacity?:number}) {
  return <mesh position={position} rotation={rotation}><boxGeometry args={size}/>{glow ? <meshBasicMaterial color={color} toneMapped={false}/> : <meshStandardMaterial color={color} metalness={opacity<1?.25:.65} roughness={opacity<1?.22:.32} transparent={opacity<1} opacity={opacity} depthWrite={opacity>=1}/>}</mesh>
}

function Cabin({light}: {light: boolean}) {
  const wall = light ? '#8399aa' : '#25394b', edges = light ? '#c8d7df' : '#51697b'
  const backing = useMemo(() => {
    const wallShape = polygon([[-20,-12],[20,-12],[20,12],[-20,12]])
    wallShape.holes.push(new THREE.Path(polygon(windowPoints).getPoints().reverse()))
    return new THREE.ShapeGeometry(wallShape)
  }, [])
  useEffect(() => () => backing.dispose(), [backing])
  return <group>
    <mesh geometry={backing} position={[0,0,-5.35]}><meshStandardMaterial color={wall} metalness={.22} roughness={.22} side={THREE.DoubleSide} transparent opacity={light?.18:.24} depthWrite={false}/></mesh>
    <group position={[0,0,-5]}><Frame scale={1.09} color={edges}/></group>
    <group position={[0,0,-4.68]}><Frame scale={1.012} color={light ? '#bcebf2' : '#61cddd'} depth={.035} bevel={.012} metallic={false}/></group>
    <group position={[0,0,-5.1]}><Frame scale={1.16} color={light ? '#566f82' : '#111f2c'} depth={.17} bevel={.07}/></group>
    <Beam position={[0,5.5,2]} size={[25,.7,17]} color={wall}/>
    <Beam position={[0,-3.45,2]} size={[28,.35,25]} color={light ? '#6c8193' : '#192b3c'}/>
    {[-9.6,9.6].map(x => <group key={x}>
      <Beam position={[x,.7,2]} size={[1.6,10,20]} color={wall} opacity={light?.16:.22}/>
      <Beam position={[x*.95,1,1]} size={[.13,8.2,.3]} color={edges}/>
      <Beam position={[x*.93,2,1.2]} size={[.045,4.2,.08]} color="#84e6ee" glow/>
      {[0,3.8,7].map(z => <Beam key={z} position={[x*.95,-.2,z]} size={[.65,1.6,.12]} color={light ? '#354b5d' : '#0e1b28'}/>)}
    </group>)}
    {[-2,2.8,7].map(z => <group key={z}>
      <Beam position={[0,4.85,z]} size={[20,.5,.55]} color={edges}/>
      <Beam position={[0,4.55,z+.1]} size={[13,.045,.18]} color="#b4e3ec" glow/>
      <Beam position={[-7,4.57,z+.1]} size={[1.5,.045,.18]} color="#d28b4a" glow/>
      <Beam position={[7,4.57,z+.1]} size={[1.5,.045,.18]} color="#d28b4a" glow/>
    </group>)}
    {[-9,-6,-3,0,3,6,9].map(x => <Beam key={'f'+x} position={[x,-3.258,1]} size={[.022,.012,25]} color={light ? '#536d80' : '#355065'}/>)}
    {[-5,-2,1,4,7,10].map(z => <Beam key={'r'+z} position={[0,-3.253,z]} size={[23,.018,.025]} color={light ? '#526d7e' : '#3b5365'}/>)}
    {[-7.7,7.7].map(x => <Beam key={'led'+x} position={[x,-3.23,1.2]} size={[.07,.018,22]} color="#62cbd9" glow/>)}
    {[-7.4,7.4].flatMap(x => [-1.5,0,1.5,3].map(y => <mesh key={x+':'+y} position={[x,y,-4.55]} rotation={[Math.PI/2,0,0]}><cylinderGeometry args={[.055,.055,.07,10]}/><meshStandardMaterial color={light ? '#cad8df' : '#8aa4b7'} metalness={.9} roughness={.2}/></mesh>))}
    <Beam position={[0,-2.96,-4.6]} size={[15,.28,.6]} color={edges}/>
    <Beam position={[0,-2.79,-4.2]} size={[11,.025,.12]} color="#6bdeed" glow/>
    <Beam position={[-8.9,-1,0]} size={[.4,.12,2]} color="#dd9654"/>
  </group>
}

const planetVertex = `varying vec3 vPosition; varying vec3 vNormal; varying vec3 vWorld;
void main(){vPosition=position;vNormal=normalize(mat3(modelMatrix)*normal);vWorld=(modelMatrix*vec4(position,1.)).xyz;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`
const planetFragment = `precision highp float; varying vec3 vPosition; varying vec3 vNormal; varying vec3 vWorld;
float hash(vec3 p){return fract(sin(dot(p,vec3(127.1,311.7,74.7)))*43758.5453);}
float noise(vec3 p){vec3 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){float n=0.;float a=.52;for(int i=0;i<5;i++){n+=a*noise(p);p=p*2.03+vec3(3.2,1.7,5.4);a*=.5;}return n;}
void main(){vec3 p=normalize(vPosition);float land=smoothstep(.48,.57,fbm(p*4.5));vec3 ocean=mix(vec3(.025,.14,.29),vec3(.09,.35,.47),fbm(p*9.));vec3 terrain=mix(vec3(.14,.24,.22),vec3(.34,.39,.29),fbm(p*14.));vec3 base=mix(ocean,terrain,land);float cloud=smoothstep(.53,.69,fbm(p*11.+fbm(p*4.)*2.));base=mix(base,vec3(.76,.85,.85),cloud*.84);float light=max(dot(normalize(vNormal),normalize(vec3(-.8,.7,1.))),0.);base*=.10+light*1.1;float rim=pow(1.-max(dot(normalize(cameraPosition-vWorld),normalize(vNormal)),0.),3.);gl_FragColor=vec4(base+vec3(.16,.48,.66)*rim*.9,1.);}`

function Satellite() {
  const textures=useMemo(()=>{
    const cells=document.createElement('canvas');cells.width=512;cells.height=256
    const ctx=cells.getContext('2d')!
    ctx.fillStyle='#101f32';ctx.fillRect(0,0,512,256)
    for(let row=0;row<5;row++)for(let col=0;col<12;col++){
      const x=col*42+4,y=row*50+4
      const gradient=ctx.createLinearGradient(x,y,x+37,y+43)
      gradient.addColorStop(0,(row+col)%3===0?'#245680':'#183e6e');gradient.addColorStop(.5,'#10254d');gradient.addColorStop(1,'#315d8c')
      ctx.fillStyle=gradient;ctx.fillRect(x,y,37,43)
      ctx.strokeStyle='#86a9be';ctx.lineWidth=.65;ctx.strokeRect(x,y,37,43)
      ctx.strokeStyle='#74a2c066';ctx.lineWidth=.45
      for(let line=1;line<8;line++){ctx.beginPath();ctx.moveTo(x,y+line*5);ctx.lineTo(x+37,y+line*5);ctx.stroke()}
      ctx.fillStyle='#bdccd0';ctx.fillRect(x+11,y,1,43);ctx.fillRect(x+25,y,1,43)
    }
    const foil=document.createElement('canvas');foil.width=128;foil.height=128
    const gold=foil.getContext('2d')!;gold.fillStyle='#a3a3a3';gold.fillRect(0,0,128,128)
    for(let i=0;i<70;i++){
      const x=(i*47.3)%128,y=(i*73.7)%128
      gold.strokeStyle=i%2?'#d9d9d9':'#646464';gold.lineWidth=i%3===0?1.1:.5
      gold.beginPath();gold.moveTo(x,y);gold.lineTo((x+25+i*3)%128,(y+11+i)%128);gold.lineTo((x+43)%128,(y+37)%128);gold.stroke()
    }
    const solarMap=new THREE.CanvasTexture(cells);solarMap.colorSpace=THREE.SRGBColorSpace;solarMap.anisotropy=4
    const foilBump=new THREE.CanvasTexture(foil)
    return {solarMap,foilBump}
  },[])
  const dish=useMemo(()=>new THREE.LatheGeometry(Array.from({length:17},(_,i)=>{const r=i/16*.48;return new THREE.Vector2(Math.max(.001,r),r*r*.75)}),32),[])
  useEffect(()=>()=>{textures.solarMap.dispose();textures.foilBump.dispose();dish.dispose()},[textures,dish])
  return <group position={[-6.5,4.3,-18]} rotation={[.11,.27,-.22]} scale={.95}>
    <Beam position={[0,0,0]} size={[7,.1,.12]} color="#a7bfce"/>
    <mesh><boxGeometry args={[1.2,1.35,1.1]}/><meshStandardMaterial color="#cfaa57" metalness={.86} roughness={.3} bumpMap={textures.foilBump} bumpScale={.065} envMapIntensity={1.7}/></mesh>
    <mesh position={[0,0,.58]}><boxGeometry args={[1.02,1.16,.08]}/><meshStandardMaterial color="#bbc9d0" metalness={.9} roughness={.25}/></mesh>
    {[-.56,.56].map(x=><Beam key={x} position={[x,0,.63]} size={[.055,1.35,.08]} color="#d6e0e5"/>)}
    {[-.61,.61].map(y=><Beam key={y} position={[0,y,.63]} size={[1.18,.05,.08]} color="#d6e0e5"/>)}
    {Array.from({length:7},(_,i)=><Beam key={i} position={[-.68,-.49+i*.16,0]} size={[.13,.075,.88]} color="#c2d1d8"/>)}
    <group position={[0,.12,.65]} rotation={[Math.PI/2,0,0]}>
      <mesh geometry={dish}><meshStandardMaterial color="#d4dfe3" metalness={.93} roughness={.22} side={THREE.DoubleSide}/></mesh>
      <mesh position={[0,.17,0]}><cylinderGeometry args={[.048,.055,.34,12]}/><meshStandardMaterial color="#8dabbc" metalness={.8} roughness={.28}/></mesh>
      <mesh position={[0,.35,0]}><sphereGeometry args={[.07,12,8]}/><meshStandardMaterial color="#bcced7" metalness={.9} roughness={.18}/></mesh>
    </group>
    <Beam position={[.38,.97,-.14]} size={[.026,.65,.026]} color="#d2dce1"/>
    <mesh position={[.38,1.3,-.14]}><sphereGeometry args={[.05,10,8]}/><meshBasicMaterial color="#a6e8f5" toneMapped={false}/></mesh>
    <mesh position={[0,-.79,0]}><cylinderGeometry args={[.24,.32,.24,16]}/><meshStandardMaterial color="#40566b" metalness={.83} roughness={.3}/></mesh>
    {[-1,1].map(side=><group key={side} position={[side*2.55,0,0]} rotation={[0,side*-.09,0]}>
      <mesh><boxGeometry args={[3.15,1.96,.075]}/><meshStandardMaterial color="#7d98ac" metalness={.85} roughness={.25}/></mesh>
      <mesh position={[0,0,.048]}><planeGeometry args={[3.04,1.84]}/><meshPhysicalMaterial map={textures.solarMap} metalness={.5} roughness={.24} clearcoat={.8} clearcoatRoughness={.19} envMapIntensity={1.3}/></mesh>
      {[-.97,.97].map(y=><Beam key={y} position={[0,y,.06]} size={[3.2,.035,.075]} color="#c5d4dd"/>)}
      {[-1.57,0,1.57].map(x=><Beam key={x} position={[x,0,.06]} size={[.025,1.95,.07]} color="#becdd6"/>)}
      <mesh position={[-side*1.68,0,0]} rotation={[0,0,Math.PI/2]}><cylinderGeometry args={[.12,.12,.25,12]}/><meshStandardMaterial color="#d0a25d" metalness={.82} roughness={.3}/></mesh>
    </group>)}
  </group>
}

function Exterior({animate}: {animate:boolean}) {
  const earth=useRef<THREE.Mesh>(null)
  useFrame((_,delta)=>{if(animate && earth.current)earth.current.rotation.y+=Math.min(delta,.05)*.03})
  return <group>
    <mesh position={[0,0,-65]}><planeGeometry args={[160,110]}/><meshBasicMaterial color="#030c1a"/></mesh>
    <mesh ref={earth} position={[7,-9,-26]} rotation={[0,.2,-.27]}><sphereGeometry args={[13,64,40]}/><shaderMaterial vertexShader={planetVertex} fragmentShader={planetFragment}/></mesh>
    <mesh position={[7,-9,-26]}><sphereGeometry args={[13.13,48,28]}/><meshBasicMaterial color="#65bde1" transparent opacity={.055} side={THREE.BackSide} depthWrite={false}/></mesh>
    <Satellite/>
  </group>
}

const particlesVertex = `attribute float aSize;attribute float aPhase;uniform float uTime;uniform float uBoost;uniform float uDust;uniform float uPixelRatio;varying float vAlpha;varying vec3 vTint;
void main(){vec3 p=position;if(uDust>.5){p.x+=sin(uTime*.11+aPhase)*.3;p.y+=sin(uTime*.09+aPhase*2.)*.22;}vec4 mv=modelViewMatrix*vec4(p,1.);gl_Position=projectionMatrix*mv;float pulse=.5+.5*sin(uTime*(.48+fract(aPhase)*.72)+aPhase);float flicker=uDust>.5?.65+.35*pulse:.38+.62*pow(pulse,2.);vAlpha=flicker*(.7+uBoost*.3);vTint=uDust>.5?vec3(1.):mix(vec3(.78,.89,1.),vec3(1.,.91,.76),step(.83,fract(aPhase*7.)));gl_PointSize=clamp(aSize*uPixelRatio*(uDust>.5?12./max(3.,-mv.z):1.),1.,18.);}`
const particlesFragment = `uniform vec3 uColor;uniform float uDust;varying float vAlpha;varying vec3 vTint;void main(){vec2 uv=gl_PointCoord-.5;float d=length(uv)*2.;if(d>1.)discard;float alpha;if(uDust>.5){alpha=pow(1.-d,1.6);}else{float core=exp(-d*d*25.);float halo=exp(-d*d*4.)*.24;float cross=(pow(max(0.,1.-abs(uv.x)*28.),3.)*pow(max(0.,1.-abs(uv.y)*2.),2.)+pow(max(0.,1.-abs(uv.y)*28.),3.)*pow(max(0.,1.-abs(uv.x)*2.),2.))*.25;alpha=core+halo+cross;}gl_FragColor=vec4(uColor*vTint,alpha*vAlpha);}`

function Particles({dust, animate, focused, sending, light}: {dust: boolean} & Pick<SceneProps,'animate'|'focused'|'sending'|'light'>) {
  const material = useRef<THREE.ShaderMaterial>(null)
  const ratio = useThree(state => state.viewport.dpr)
  const geometry = useMemo(() => {
    let seed=137
    const random=()=>{seed=seed*16807%2147483647;return seed/2147483647}
    const count=dust?140:1600, positions=new Float32Array(count*3),sizes=new Float32Array(count),phases=new Float32Array(count)
    for(let i=0;i<count;i++){positions[i*3]=(random()-.5)*(dust?22:74);positions[i*3+1]=(random()-.5)*(dust?12:40);positions[i*3+2]=dust?-3+random()*11:-35-random()*18;const magnitude=random();sizes[i]=dust?2+magnitude*5:magnitude>.97?5+(magnitude-.97)*95:1.5+magnitude*2.2;phases[i]=random()*Math.PI*2}
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(positions,3));geo.setAttribute('aSize',new THREE.BufferAttribute(sizes,1));geo.setAttribute('aPhase',new THREE.BufferAttribute(phases,1));return geo
  },[dust])
  const uniforms=useMemo(()=>({uTime:{value:0},uBoost:{value:0},uDust:{value:dust?1:0},uPixelRatio:{value:ratio},uColor:{value:new THREE.Color(dust ? light?'#187c9c':'#a1e7ee':'#cfdfeb')}}),[dust,light,ratio])
  useEffect(()=>()=>geometry.dispose(),[geometry])
  useFrame((state,delta)=>{if(!material.current)return;if(animate)material.current.uniforms.uTime.value+=Math.min(delta,.05);material.current.uniforms.uBoost.value=THREE.MathUtils.damp(material.current.uniforms.uBoost.value,sending?2:focused?1:0,4,Math.min(delta,.05));void state})
  return <points geometry={geometry} frustumCulled={false}><shaderMaterial ref={material} uniforms={uniforms} vertexShader={particlesVertex} fragmentShader={particlesFragment} transparent depthWrite={false} blending={dust&&light?THREE.NormalBlending:THREE.AdditiveBlending}/></points>
}

function Reflections({light}: {light:boolean}) {
  const {scene,invalidate}=useThree()
  useEffect(()=>{
    const faces=Array.from({length:6},(_,i)=>{const canvas=document.createElement('canvas');canvas.width=64;canvas.height=64;const ctx=canvas.getContext('2d')!;const gradient=ctx.createLinearGradient(0,0,64,64);gradient.addColorStop(0,light?'#a6c0cd':'#142f42');gradient.addColorStop(.5,light?'#718995':'#45677a');gradient.addColorStop(1,light?'#d2dce2':'#071625');ctx.fillStyle=gradient;ctx.fillRect(0,0,64,64);ctx.fillStyle=i===2?'#e6eff5':'#6cb4c6';ctx.fillRect(7,5,3,53);ctx.fillRect(16,7,37,2);return canvas})
    const texture=new THREE.CubeTexture(faces);texture.needsUpdate=true;const old=scene.environment;scene.environment=texture;invalidate()
    return()=>{scene.environment=old;texture.dispose()}
  },[scene,light,invalidate])
  return null
}

export default function StationScene(props: SceneProps) {
  return <Canvas className="station-webgl" camera={{position:[0,.75,12],fov:48,near:.1,far:120}} dpr={[1,1.4]} frameloop="demand" gl={{alpha:true,antialias:false,powerPreference:'low-power'}} onCreated={({gl,camera})=>{camera.lookAt(0,.55,-5);gl.setClearColor(0x020811,0);props.onReady()}} onContextMenu={event=>event.preventDefault()}>
    <ContextGuard onFailure={props.onFailure}/><Reflections light={props.light}/>
    <ambientLight intensity={props.light ? .9 : .48}/><hemisphereLight args={['#abcfe0','#0a1826',props.light?1.2:.65]}/>
    <directionalLight position={[-4,8,7]} intensity={props.light?2.3:1.5} color="#c7e6f2"/>
    <pointLight position={[-6,3,6]} intensity={props.light?50:75} color="#70dbef" distance={30} decay={2}/>
    <pointLight position={[8,3,-2]} intensity={30} color="#edb785" distance={20} decay={2}/>
    <Exterior animate={props.animate}/><Particles {...props} dust={false}/><Cabin light={props.light}/><Particles {...props} dust/>
    <FrameTicker animate={props.animate}/>
  </Canvas>
}

function FrameTicker({animate}: {animate:boolean}) {
  const invalidate=useThree(state=>state.invalidate)
  useEffect(()=>{if(!animate)return;const timer=window.setInterval(invalidate,1000/30);return()=>clearInterval(timer)},[animate,invalidate])
  return null
}

function ContextGuard({onFailure}: {onFailure:()=>void}) {
  const {gl}=useThree()
  useEffect(()=>{const canvas=gl.domElement;const lost=(event:Event)=>{event.preventDefault();onFailure()};canvas.addEventListener('webglcontextlost',lost);return()=>canvas.removeEventListener('webglcontextlost',lost)},[gl,onFailure])
  return null
}
