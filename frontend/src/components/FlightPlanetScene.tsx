import { useEffect, useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import type { PlanetMarker } from './FlightPlanet'
import { planetTheme } from '../techPlanets'

const vertex=`
varying vec3 vLocal; varying vec3 vNormal; varying vec3 vWorld;
void main(){vLocal=position;vNormal=normalize(mat3(modelMatrix)*normal);vWorld=(modelMatrix*vec4(position,1.)).xyz;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`
const noise=`
float hash(vec3 p){return fract(sin(dot(p,vec3(127.1,311.7,74.7)))*43758.5453);}
float noise(vec3 p){vec3 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
float fbm(vec3 p){float v=0.,a=.53;for(int i=0;i<4;i++){v+=noise(p)*a;p=p*2.03+vec3(3.1,5.7,1.2);a*=.5;}return v;}`
const surfaceFragment=`
precision highp float;
varying vec3 vLocal; varying vec3 vNormal; varying vec3 vWorld;
uniform vec3 core; uniform vec3 energy; uniform vec3 accent;
uniform float time; uniform float seed; uniform float mode;
${noise}
float line(float value,float width){return 1.-smoothstep(width,width+max(fwidth(value),.002),abs(value));}
void main(){
  vec3 p=normalize(vLocal),n=normalize(vNormal),view=normalize(cameraPosition-vWorld);
  vec2 uv=vec2(atan(p.z,p.x)/6.2831853+.5,asin(clamp(p.y,-1.,1.))/3.14159265+.5);
  float grain=fbm(p*4.+seed),detail=fbm(p*18.+seed);
  vec3 metal=mix(core*.52,core*1.7,grain)*(.5+max(dot(n,normalize(vec3(-.8,.9,1.))),0.)*.8);
  float cells=36.+mode*4.; vec2 lattice=uv*vec2(cells,20.);
  float grid=max(line(fract(lattice.x)-.5,.012),line(fract(lattice.y)-.5,.012));
  float circuit=line(grain-(.48+sin(p.y*8.+seed)*.025),.009);
  float branches=line(fbm(p*8.+seed)-.49,.005)*.35;
  float poweredPanel=step(.6,noise(floor(lattice.xyx)+seed));
  vec2 dotCell=fract(uv*vec2(96.,48.))-.5;
  float beacons=exp(-dot(dotCell,dotCell)*180.)*step(.94,hash(vec3(floor(uv*vec2(96.,48.)),seed)));
  float scanY=.5+sin(time*.27+seed)*.36;
  float scan=exp(-pow((uv.y-scanY)*100.,2.));
  float rim=pow(1.-max(dot(view,n),0.),3.1);
  float pulse=.86+.14*sin(time*.9+grain*8.);
  float channels=(circuit+branches)*(.32+grain*.65);
  if(mode>2.5&&mode<3.5){channels=pow(circuit,.75)*(1.+detail*.8);metal*=.75;}
  vec3 color=metal+energy*(grid*(.08+poweredPanel*.12)+channels*.82+beacons*.85)*pulse;
  color+=accent*scan*(.4+grid*.65)+energy*rim*.85;
  float spec=pow(max(dot(reflect(-normalize(vec3(-.8,.9,1.)),n),view),0.),32.);
  color+=vec3(.5,.7,.8)*spec*.26;
  gl_FragColor=vec4(color,1.);
}`
const atmosphereFragment=`
precision highp float; varying vec3 vNormal; varying vec3 vWorld; uniform vec3 energy;
void main(){float rim=pow(1.-abs(dot(normalize(cameraPosition-vWorld),normalize(vNormal))),3.8);gl_FragColor=vec4(energy,rim*.7);}`
const flatVertex=`varying vec2 vUv;varying vec3 vLocal;void main(){vUv=uv;vLocal=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`
const haloFragment=`
precision highp float; varying vec2 vUv; uniform vec3 energy;uniform float time;
void main(){float r=length(vUv-.5)*2.;float glow=exp(-pow((r-.455)*13.,2.))*.28+exp(-r*r*5.)*.05;glow*=smoothstep(.34,.46,r)*(1.-smoothstep(.7,1.,r));gl_FragColor=vec4(energy,glow*(.92+.08*sin(time*.7)));}`
const ringFragment=`
precision highp float; varying vec3 vLocal; uniform vec3 energy; uniform vec3 accent; uniform float time;uniform float offset;
void main(){float a=atan(vLocal.y,vLocal.x)+3.14159265;float segment=step(.12,fract(a*7.));float sweep=pow(max(0.,cos(a-time*.32-offset)),18.);vec3 color=mix(energy,accent,sweep);gl_FragColor=vec4(color,(.26+segment*.28+sweep*.45));}`
const particleVertex=`
attribute float size;attribute float phase;uniform float time;uniform float pixelRatio;
varying float intensity;varying float tint;
void main(){float angle=position.x+time*(.08+phase*.025);float r=position.y;vec3 p=vec3(cos(angle)*r,sin(angle)*r*.4+position.z, sin(angle)*r*.5);p.xy=mat2(.96,-.28,.28,.96)*p.xy;gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);intensity=.4+.6*pow(.5+.5*sin(phase*9.+time*.75),2.);tint=phase;gl_PointSize=size*pixelRatio*(.8+intensity*.3);}`
const particleFragment=`
precision highp float;uniform vec3 energy;uniform vec3 accent;varying float intensity;varying float tint;
void main(){vec2 p=gl_PointCoord-.5;float core=exp(-dot(p,p)*35.);float star=exp(-abs(p.x)*70.-abs(p.y)*10.)+exp(-abs(p.y)*70.-abs(p.x)*10.);float alpha=(core+star*.28)*intensity;if(alpha<.015)discard;gl_FragColor=vec4(mix(energy,accent,step(.72,tint))+vec3(core*.2),alpha);}`

function EnergyParticles({radius,compact,uniforms}: {radius:number;compact:boolean;uniforms:Record<string,THREE.IUniform>}) {
  const data=useMemo(()=>{
    const count=compact?64:240,positions=new Float32Array(count*3),sizes=new Float32Array(count),phases=new Float32Array(count)
    let seed=1949
    const random=()=>{seed=(seed*16807)%2147483647;return seed/2147483647}
    for(let i=0;i<count;i++){
      positions[i*3]=random()*Math.PI*2
      positions[i*3+1]=radius*(1.15+random()*.65)
      positions[i*3+2]=(random()-.5)*radius*.65
      sizes[i]=(i%13===0?6:1.4+random()*2.4)*(compact?.8:1)
      phases[i]=random()
    }
    return {positions,sizes,phases}
  },[radius,compact])
  return <points frustumCulled={false}><bufferGeometry><bufferAttribute attach="attributes-position" args={[data.positions,3]}/><bufferAttribute attach="attributes-size" args={[data.sizes,1]}/><bufferAttribute attach="attributes-phase" args={[data.phases,1]}/></bufferGeometry><shaderMaterial vertexShader={particleVertex} fragmentShader={particleFragment} uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending}/></points>
}

function TechGlobe({index,position,radius,animate,compact}: {index:number;position:[number,number,number];radius:number;animate:boolean;compact:boolean}) {
  const globe=useRef<THREE.Mesh>(null)
  const rings=useRef<THREE.Group>(null)
  const {gl}=useThree()
  const theme=planetTheme(index)
  const uniforms=useMemo(()=>({
    core:{value:new THREE.Color(theme.core)},energy:{value:new THREE.Color(theme.light)},accent:{value:new THREE.Color(theme.accent)},
    time:{value:0},seed:{value:index*3.17},mode:{value:index%6},offset:{value:index*.7},pixelRatio:{value:gl.getPixelRatio()},
  }),[index,theme,gl])
  useFrame((_,delta)=>{
    if(!animate)return
    const step=Math.min(delta,.06)
    uniforms.time.value+=step
    uniforms.pixelRatio.value=gl.getPixelRatio()
    if(globe.current)globe.current.rotation.y+=step*.065
    if(rings.current)rings.current.rotation.z+=step*.018
  })
  return <group position={position}>
    <mesh position={[0,0,-radius*.25]}><planeGeometry args={[radius*4.5,radius*4.5]}/><shaderMaterial vertexShader={flatVertex} fragmentShader={haloFragment} uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending}/></mesh>
    <mesh ref={globe} rotation={[.12,.5,-.18]}><sphereGeometry args={[radius,80,56]}/><shaderMaterial vertexShader={vertex} fragmentShader={surfaceFragment} uniforms={uniforms}/></mesh>
    <mesh><sphereGeometry args={[radius*1.035,56,40]}/><shaderMaterial vertexShader={vertex} fragmentShader={atmosphereFragment} uniforms={uniforms} transparent depthWrite={false} blending={THREE.AdditiveBlending}/></mesh>
    <group ref={rings} rotation={[.1,0,index*.15]}>
      <group rotation={[1.14+index*.04,.18,-.38]}>
        <mesh><ringGeometry args={[radius*1.28,radius*1.296,160]}/><shaderMaterial vertexShader={flatVertex} fragmentShader={ringFragment} uniforms={uniforms} transparent side={THREE.DoubleSide} depthWrite={false} blending={THREE.AdditiveBlending}/></mesh>
        <mesh><ringGeometry args={[radius*1.33,radius*1.345,160]}/><meshBasicMaterial color={theme.light} transparent opacity={.12} side={THREE.DoubleSide} depthWrite={false} blending={THREE.AdditiveBlending}/></mesh>
        <mesh><ringGeometry args={[radius*1.27,radius*1.36,160]}/><meshBasicMaterial color={theme.light} transparent opacity={.045} side={THREE.DoubleSide} depthWrite={false} blending={THREE.AdditiveBlending}/></mesh>
      </group>
      <group rotation={[.56,-.86,.68+index*.18]}><mesh><ringGeometry args={[radius*1.48,radius*1.488,144]}/><shaderMaterial vertexShader={flatVertex} fragmentShader={ringFragment} uniforms={uniforms} transparent side={THREE.DoubleSide} depthWrite={false} blending={THREE.AdditiveBlending}/></mesh></group>
    </group>
    <EnergyParticles radius={radius} compact={compact} uniforms={uniforms}/>
  </group>
}

function Contents({index,markers,animate,fail}: {index:number;markers?:PlanetMarker[];animate:boolean;fail:()=>void}) {
  const {viewport,invalidate,gl}=useThree()
  useEffect(()=>{if(!animate)return;const timer=setInterval(invalidate,1000/30);return()=>clearInterval(timer)},[animate,invalidate])
  useEffect(()=>{const lost=(event:Event)=>{event.preventDefault();fail()};gl.domElement.addEventListener('webglcontextlost',lost);return()=>gl.domElement.removeEventListener('webglcontextlost',lost)},[gl,fail])
  const points=markers || [{x:44,y:47,index}]
  return <>{points.map((point,i)=>{
    const radius=markers?Math.min(viewport.width/(markers.length>3?14:11),1.06)*(point.selected?1.08:.88):Math.min(viewport.width*.195,viewport.height*.265)
    return <TechGlobe key={markers?i:'current'} index={point.index} position={[(point.x/100-.5)*viewport.width,(.5-point.y/100)*viewport.height,0]} radius={radius} animate={animate} compact={!!markers}/>
  })}</>
}

export default function FlightPlanetScene({index,markers,animate,ready,fail}: {index:number;markers?:PlanetMarker[];animate:boolean;ready:()=>void;fail:()=>void}) {
  return <Canvas orthographic camera={{position:[0,0,10],zoom:50,near:.1,far:40}} dpr={[1,1.5]} frameloop="demand" gl={{alpha:true,antialias:true,powerPreference:'low-power'}} onCreated={({gl})=>{gl.setClearColor(0,0);gl.debug.onShaderError=()=>fail();ready()}}>
    <Contents index={index} markers={markers} animate={animate} fail={fail}/>
  </Canvas>
}
