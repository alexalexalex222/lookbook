'use client'

import { motion, useMotionValue, useTransform } from 'framer-motion'
import { MapPin, Phone, Menu, X, ChevronLeft, ChevronRight, Mountain, Trees, HardHat, MoveRight } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'

// Before/After Slider Component
function BeforeAfterSlider() {
  const [sliderPosition, setSliderPosition] = useState(50)
  const containerRef = useRef<HTMLDivElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  const handleMove = (clientX: number) => {
    if (!containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const x = clientX - rect.left
    const percentage = (x / rect.width) * 100
    setSliderPosition(Math.max(0, Math.min(100, percentage)))
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return
    handleMove(e.clientX)
  }

  const handleTouchMove = (e: React.TouchEvent) => {
    if (!isDragging) return
    handleMove(e.touches[0].clientX)
  }

  useEffect(() => {
    const handleMouseUp = () => setIsDragging(false)
    window.addEventListener('mouseup', handleMouseUp)
    window.addEventListener('touchend', handleMouseUp)
    return () => {
      window.removeEventListener('mouseup', handleMouseUp)
      window.removeEventListener('touchend', handleMouseUp)
    }
  }, [])

  return (
    <div 
      ref={containerRef}
      className="relative w-full h-[400px] md:h-[500px] overflow-hidden cursor-ew-resize select-none shadow-2xl"
      onMouseMove={handleMouseMove}
      onMouseDown={() => setIsDragging(true)}
      onTouchMove={handleTouchMove}
      onTouchStart={() => setIsDragging(true)}
    >
      {/* After Image */}
      <img
        src="/images/IMG_1954 copy 3.JPG"
        alt="After"
        className="absolute inset-0 w-full h-full object-cover"
        draggable={false}
      />
      
      <motion.div 
        className="absolute top-4 right-4 bg-[#FFD700] text-black px-4 py-2 text-sm font-bold shadow-lg z-10"
        initial={{ opacity: 0, x: 20 }}
        whileInView={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.5 }}
      >
        AFTER
      </motion.div>
      
      {/* Before Image */}
      <div
        className="absolute inset-0 overflow-hidden"
        style={{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }}
      >
        <img
          src="/images/IMG_1717 copy 3.JPG"
          alt="Before"
          className="absolute inset-0 w-full h-full object-cover"
          draggable={false}
        />
        <motion.div 
          className="absolute top-4 left-4 bg-black/80 text-white px-4 py-2 text-sm font-bold shadow-lg"
          initial={{ opacity: 0, x: -20 }}
          whileInView={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.5 }}
        >
          BEFORE
        </motion.div>
      </div>

      {/* Slider Handle */}
      <div 
        className="absolute top-0 bottom-0 w-1 bg-[#FFD700] cursor-ew-resize z-20 shadow-lg"
        style={{ left: `${sliderPosition}%`, transform: 'translateX(-50%)' }}
      >
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-14 h-14 bg-[#FFD700] flex items-center justify-center shadow-2xl border-4 border-black">
          <ChevronLeft className="w-5 h-5 text-black" />
          <ChevronRight className="w-5 h-5 text-black" />
        </div>
      </div>

      <motion.div 
        className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-black/80 text-white px-6 py-3 text-sm backdrop-blur-sm"
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.8 }}
      >
        ← DRAG TO COMPARE →
      </motion.div>
    </div>
  )
}

// Destruction Slider
function DestructionSlider() {
  const x = useMotionValue(0)
  const width = useTransform(x, [0, 300], ['0%', '100%'])

  return (
    <div className="relative h-32 bg-[#2a2a2a] overflow-hidden border border-white/10">
      <div className="absolute inset-0 flex items-center px-4">
        <span className="text-white/50 text-sm tracking-wider">DRAG THE DOZER TO CLEAR</span>
      </div>
      <motion.div 
        className="absolute left-0 top-0 bottom-0 bg-gradient-to-r from-[#FFD700]/30 to-transparent"
        style={{ width }}
      />
      <motion.div
        drag="x"
        dragConstraints={{ left: 0, right: 300 }}
        dragElastic={0}
        style={{ x }}
        className="absolute top-1/2 -translate-y-1/2 cursor-grab active:cursor-grabbing z-10"
      >
        <div className="bg-[#FFD700] text-black p-3 flex items-center gap-2 shadow-lg">
          <MoveRight className="w-6 h-6" />
          <span className="font-bold tracking-wider">PUSH</span>
        </div>
      </motion.div>
    </div>
  )
}

// Tri-State Map
function TriStateMap() {
  const locations = [
    { name: 'Blairsville', x: 52, y: 55 },
    { name: 'Blue Ridge', x: 28, y: 48 },
    { name: 'Hiawassee', x: 72, y: 35 },
  ]

  const counties = [
    { name: 'Union', path: 'M85,80 L140,60 L160,120 L130,160 L75,140 Z', center: { x: 115, y: 110 } },
    { name: 'Fannin', path: 'M30,50 L85,80 L75,140 L40,130 L20,90 Z', center: { x: 60, y: 95 } },
    { name: 'Towns', path: 'M140,60 L200,40 L220,80 L190,110 L160,120 Z', center: { x: 175, y: 80 } },
  ]

  return (
    <div className="relative w-full h-[450px] bg-gradient-to-br from-green-900 via-green-800 to-emerald-900 overflow-hidden shadow-2xl">
      <svg className="absolute inset-0 w-full h-full opacity-10" viewBox="0 0 400 350" preserveAspectRatio="xMidYMid slice">
        <defs>
          <pattern id="topo" patternUnits="userSpaceOnUse" width="60" height="40">
            <path d="M0,20 Q15,10 30,20 T60,20" fill="none" stroke="#90EE90" strokeWidth="0.8"/>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#topo)"/>
      </svg>

      <svg className="absolute inset-4 w-[calc(100%-32px)] h-[calc(100%-32px)]" viewBox="0 0 240 180">
        {counties.map((county, index) => (
          <motion.g key={county.name}>
            <motion.path
              d={county.path}
              fill={index === 0 ? "#2d5016" : index === 1 ? "#3d6b1e" : "#1e3d0f"}
              stroke="#FFD700"
              strokeWidth="2"
              initial={{ pathLength: 0 }}
              whileInView={{ pathLength: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 1.5, delay: index * 0.3 }}
            />
            <text x={county.center.x} y={county.center.y} fill="white" fontSize="11" fontWeight="bold" textAnchor="middle">
              {county.name.toUpperCase()}
            </text>
          </motion.g>
        ))}

        {locations.map((loc, i) => (
          <motion.g key={loc.name} initial={{ scale: 0 }} whileInView={{ scale: 1 }} transition={{ delay: 1.5 + i * 0.2 }}>
            <circle cx={loc.x * 2.4} cy={loc.y * 1.8} r="12" fill="none" stroke="#FFD700" strokeWidth="1">
              <animate attributeName="r" values="8;16;8" dur="2s" repeatCount="indefinite" />
            </circle>
            <circle cx={loc.x * 2.4} cy={loc.y * 1.8} r="6" fill="#FFD700" stroke="black" strokeWidth="2" />
            <rect x={loc.x * 2.4 - 35} y={loc.y * 1.8 - 35} width="70" height="20" fill="black" opacity="0.8" />
            <text x={loc.x * 2.4} y={loc.y * 1.8 - 21} fill="white" fontSize="9" fontWeight="bold" textAnchor="middle">
              {loc.name.toUpperCase()}
            </text>
          </motion.g>
        ))}
      </svg>

      <motion.div 
        className="absolute bottom-4 right-4 bg-black/80 text-white px-4 py-3 border-l-4 border-[#FFD700]"
        initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} transition={{ delay: 2 }}
      >
        <div className="font-bold text-sm">SERVICE AREA</div>
        <div className="text-xs text-[#FFD700]">Union • Fannin • Towns</div>
      </motion.div>
    </div>
  )
}

export default function Home() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  return (
    <main className="min-h-screen bg-[#1a1a1a]">
      <div className="fixed inset-0 dirt-texture pointer-events-none z-50" />

      {/* Navbar */}
      <nav className="sticky top-0 z-40 bg-[#1a1a1a]/95 backdrop-blur border-b border-white/10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className="flex items-center gap-3">
              <div className="w-10 h-10 bg-[#FFD700] flex items-center justify-center">
                <Mountain className="w-6 h-6 text-black" />
              </div>
              <div>
                <span className="font-impact text-xl text-white block leading-none">HOLLAND GRADING</span>
                <span className="text-[#FFD700] text-xs tracking-widest">DIRT DYNASTY THEME</span>
              </div>
            </motion.div>
            
            <div className="hidden md:flex items-center gap-8">
              <a href="#work" className="text-white/70 hover:text-[#FFD700] transition-colors tracking-wider">OUR WORK</a>
              <a href="#map" className="text-white/70 hover:text-[#FFD700] transition-colors tracking-wider">SERVICE AREA</a>
              <a href="#contact" className="bg-[#FFD700] text-black px-6 py-2 font-bold hover:bg-[#E6C200] transition-colors">
                GET QUOTE
              </a>
            </div>

            <button className="md:hidden text-white" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
              {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="md:hidden bg-[#2a2a2a] border-t border-white/10">
            <div className="px-4 py-2 space-y-2">
              <a href="#work" className="block py-2 text-white/70">OUR WORK</a>
              <a href="#map" className="block py-2 text-white/70">SERVICE AREA</a>
              <a href="#contact" className="block py-2 text-[#FFD700]">GET QUOTE</a>
            </div>
          </motion.div>
        )}
      </nav>

      {/* Hero */}
      <section className="relative min-h-[90vh] flex items-center justify-center overflow-hidden">
        <div className="absolute inset-0">
          <img src="/images/Screenshot 2026-01-31 at 12.45.42 PM copy 2.png" alt="" className="w-full h-full object-cover opacity-50" />
          <div className="absolute inset-0 bg-gradient-to-t from-[#1a1a1a] via-[#1a1a1a]/60 to-transparent" />
        </div>

        <div className="relative z-10 max-w-7xl mx-auto px-4 text-center">
          <motion.div initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8 }}>
            <h1 className="text-6xl md:text-8xl lg:text-9xl font-impact text-white mb-6 leading-none tracking-tight">
              WE MOVE<br />
              <span className="text-[#FFD700]">MOUNTAINS.</span>
            </h1>
            <p className="text-2xl md:text-3xl text-white/80 mb-4 tracking-wide">
              YOU RECLAIM THE VIEW.
            </p>
            <p className="text-white/60 max-w-2xl mx-auto mb-8">
              Holland Grading LLC. Professional land clearing and grading services. Transforming North Georgia's toughest terrain since 2009.
            </p>
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
              <a href="#work" className="bg-[#FFD700] text-black px-8 py-4 font-bold text-lg hover:bg-[#E6C200] transition-colors tracking-wider">
                SEE THE TRANSFORMATION
              </a>
              <a href="tel:+17065551234" className="border-2 border-white/30 text-white px-8 py-4 font-bold text-lg hover:border-[#FFD700] hover:text-[#FFD700] transition-colors tracking-wider">
                CALL WYATT
              </a>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Before/After */}
      <section id="work" className="py-20 bg-[#2a2a2a]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="text-center mb-12">
            <h2 className="text-4xl md:text-6xl font-impact text-white mb-4">TRANSFORMATION</h2>
            <div className="w-20 h-1 bg-[#FFD700] mx-auto" />
            <p className="mt-4 text-white/60">Drag to see the dramatic before & after</p>
          </motion.div>
          <BeforeAfterSlider />
          <div className="mt-8">
            <DestructionSlider />
          </div>
        </div>
      </section>

      {/* Tri-State Map */}
      <section id="map" className="py-20 bg-[#1a1a1a]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid md:grid-cols-2 gap-12 items-center">
            <motion.div initial={{ opacity: 0, x: -30 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }}>
              <h2 className="text-4xl md:text-6xl font-impact text-white mb-4">
                TRI-STATE<br /><span className="text-[#FFD700]">SERVICE AREA</span>
              </h2>
              <div className="w-20 h-1 bg-[#FFD700] mb-6" />
              <p className="text-white/70 mb-6">
                Serving the rugged mountain terrain of North Georgia. From Blairsville to Blue Ridge to Hiawassee.
              </p>
              <div className="space-y-4">
                {[
                  { icon: MapPin, title: 'Blairsville', desc: 'Union County headquarters' },
                  { icon: Trees, title: 'Blue Ridge', desc: 'Fannin County operations' },
                  { icon: Mountain, title: 'Hiawassee', desc: 'Towns County coverage' },
                ].map((item, index) => (
                  <motion.div key={item.title} initial={{ opacity: 0, x: -20 }} whileInView={{ opacity: 1, x: 0 }} transition={{ delay: index * 0.1 }}
                    className="flex items-center gap-4 p-4 bg-[#2a2a2a]">
                    <div className="w-12 h-12 bg-[#FFD700]/20 flex items-center justify-center">
                      <item.icon className="w-6 h-6 text-[#FFD700]" />
                    </div>
                    <div>
                      <div className="font-bold text-white">{item.title}</div>
                      <div className="text-white/50 text-sm">{item.desc}</div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </motion.div>
            <motion.div initial={{ opacity: 0, x: 30 }} whileInView={{ opacity: 1, x: 0 }} viewport={{ once: true }}>
              <TriStateMap />
            </motion.div>
          </div>
        </div>
      </section>

      {/* Asymmetric Services Grid */}
      <section className="py-20 bg-[#2a2a2a]">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="text-center mb-12">
            <h2 className="text-4xl md:text-6xl font-impact text-white mb-4">THE POWER</h2>
            <div className="w-20 h-1 bg-[#FFD700] mx-auto" />
          </motion.div>

          <div className="grid md:grid-cols-3 gap-4">
            <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} className="md:col-span-2 md:row-span-2 group relative overflow-hidden">
              <div className="h-full min-h-[400px] overflow-hidden">
                <img src="/images/IMG_1717 copy 3.JPG" alt="Land Clearing" className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700" />
                <div className="absolute inset-0 bg-gradient-to-t from-black via-black/50 to-transparent" />
              </div>
              <div className="absolute bottom-0 left-0 right-0 p-8">
                <h3 className="font-impact text-3xl text-white mb-2">LAND CLEARING</h3>
                <p className="text-white/60">Complete vegetation removal</p>
              </div>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="group relative overflow-hidden">
              <div className="h-48 overflow-hidden">
                <img src="/images/Screenshot 2026-01-31 at 12.49.32 PM copy 2.png" alt="Site Prep" className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700" />
                <div className="absolute inset-0 bg-gradient-to-t from-black via-black/50 to-transparent" />
              </div>
              <div className="absolute bottom-0 left-0 right-0 p-4">
                <h3 className="font-impact text-xl text-white">SITE PREP</h3>
              </div>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="group relative overflow-hidden">
              <div className="h-48 overflow-hidden">
                <img src="/images/Screenshot 2026-01-31 at 12.49.37 PM copy 2.png" alt="Rough Grading" className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700" />
                <div className="absolute inset-0 bg-gradient-to-t from-black via-black/50 to-transparent" />
              </div>
              <div className="absolute bottom-0 left-0 right-0 p-4">
                <h3 className="font-impact text-xl text-white">ROUGH GRADING</h3>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section id="contact" className="py-20 bg-[#FFD700]">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <motion.div initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}>
            <HardHat className="w-16 h-16 text-black mx-auto mb-6" />
            <h2 className="text-4xl md:text-6xl font-impact text-black mb-4">READY TO MOVE<br />SOME DIRT?</h2>
            <p className="text-black/70 text-lg mb-8">Call Wyatt at Holland Grading for a free consultation</p>
            <a href="tel:+17065551234" className="inline-flex items-center gap-3 bg-[#1a1a1a] text-white px-8 py-4 font-bold text-xl hover:bg-[#2a2a2a] transition-colors">
              <Phone className="w-6 h-6" />
              (706) 555-1234
            </a>
          </motion.div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-[#1a1a1a] py-12 border-t border-white/10">
        <div className="max-w-7xl mx-auto px-4">
          <div className="flex flex-col md:flex-row justify-between items-center gap-6">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-[#FFD700] flex items-center justify-center">
                <Mountain className="w-6 h-6 text-black" />
              </div>
              <div>
                <span className="font-impact text-lg text-white block">HOLLAND GRADING</span>
                <span className="text-[#FFD700] text-xs tracking-widest">LLC</span>
              </div>
            </div>
            <div className="text-white/50 text-sm text-center md:text-right">
              <p>Serving Union, Fannin & Towns Counties</p>
              <p>© 2024 Holland Grading LLC</p>
            </div>
          </div>
        </div>
      </footer>
    </main>
  )
}
