import { useEffect, useRef } from 'react'
import { ArrowUpRight, Compass, Orbit, Sparkles } from 'lucide-react'
import { planetImage } from '../pathGraphics'
import { useTheme } from '../ThemeProvider'

/** A bounded, decorative canvas. It sleeps offscreen and respects reduced motion. */
export function Starfield() {
  const {theme} = useTheme()
  const canvas = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const element = canvas.current!
    const context = element.getContext('2d')
    if (!context) return
    const reduced = matchMedia('(prefers-reduced-motion: reduce)')
    const starColor = theme === 'light' ? '79,111,143' : '205,225,240'
    const glowColor = theme === 'light' ? '92,132,168' : '184,216,239'
    let width = 0, height = 0, frame = 0, last = 0, elapsed = 0
    let stars: {x: number; y: number; size: number; alpha: number; phase: number; period: number; sparkle: boolean}[] = []
    let seed = 48
    const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 }
    function resize() {
      width = window.innerWidth; height = window.innerHeight
      const ratio = Math.min(devicePixelRatio || 1, 1.5)
      element.width = Math.round(width * ratio); element.height = Math.round(height * ratio)
      context!.setTransform(ratio, 0, 0, ratio, 0, 0)
      seed = 48
      stars = Array.from({length: Math.min(480, Math.max(90, Math.floor(width * height / 2700)))}, () => ({
        x: random() * width, y: random() * height,
        size: .7 + random() * 2.1, alpha: .4 + random() * .5,
        phase: random() * Math.PI * 2, period: 2.8 + random() * 4.2,
        sparkle: random() > .8,
      }))
      draw(0)
    }
    function draw(time: number) {
      if (time - last < 45 && time) {frame = requestAnimationFrame(draw); return}
      if (time && last) elapsed += Math.min(time - last, 100) / 1000
      last = time
      context!.clearRect(0, 0, width, height)
      stars.forEach(star => {
        const wave = reduced.matches ? .65 : (1 + Math.sin(elapsed * Math.PI * 2 / star.period + star.phase)) / 2
        const brightness = star.alpha * (.16 + wave * .84) * (theme === 'light' ? .65 : 1)
        const radius = star.size * (.85 + wave * .15)
        if (star.sparkle) {
          const halo = context!.createRadialGradient(star.x, star.y, 0, star.x, star.y, radius * 5)
          halo.addColorStop(0, `rgba(${glowColor},${brightness * .35})`)
          halo.addColorStop(1, `rgba(${glowColor},0)`)
          context!.fillStyle = halo
          context!.fillRect(star.x - radius * 5, star.y - radius * 5, radius * 10, radius * 10)
          if (wave > .65) {
            const ray = radius * (2 + wave)
            context!.strokeStyle = `rgba(${starColor},${brightness * .4})`
            context!.lineWidth = .5
            context!.beginPath()
            context!.moveTo(star.x - ray, star.y); context!.lineTo(star.x + ray, star.y)
            context!.moveTo(star.x, star.y - ray); context!.lineTo(star.x, star.y + ray)
            context!.stroke()
          }
        }
        context!.fillStyle = `rgba(${starColor},${brightness})`
        context!.beginPath(); context!.arc(star.x, star.y, radius, 0, Math.PI * 2); context!.fill()
      })
      if (!reduced.matches && !document.hidden) frame = requestAnimationFrame(draw)
    }
    function resume() {cancelAnimationFrame(frame); last = 0; draw(0)}
    resize()
    window.addEventListener('resize', resumeResize)
    document.addEventListener('visibilitychange', resume)
    reduced.addEventListener('change', resume)
    function resumeResize() {cancelAnimationFrame(frame); resize()}
    return () => {cancelAnimationFrame(frame); window.removeEventListener('resize', resumeResize); document.removeEventListener('visibilitychange', resume); reduced.removeEventListener('change', resume)}
  }, [theme])
  return <div className="universe-background" aria-hidden="true"><div className="universe-nebula"/><canvas ref={canvas}/><div className="universe-noise"/></div>
}

export function ObservatoryScene() {
  return <div className="observatory-scene" aria-hidden="true">
    <div className="observatory-orbit orbit-one"/><div className="observatory-orbit orbit-two"/><div className="observatory-orbit orbit-three"/>
    <div className="hero-planet"><span className="hero-atmosphere"/><img src={planetImage(4)} alt=""/><span className="hero-terminator"/></div>
    <div className="satellite satellite-one"><img src={planetImage(0)} alt=""/></div>
    <div className="satellite satellite-two"><img src={planetImage(1)} alt=""/></div>
  </div>
}

export function JourneySteps({active}: {active: number}) {
  return <ol className="journey-steps" aria-label="探索流程">
    {['发现相似经历', '选择你的航线', '迈出下一步'].map((label, index) => <li key={label} className={active === index ? 'is-current' : active > index ? 'is-past' : ''} aria-current={active === index ? 'step' : undefined}><span>{String(index + 1).padStart(2, '0')}</span>{label}</li>)}
  </ol>
}
