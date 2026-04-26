import { motion } from "framer-motion";

/**
 * Animated renewable-energy hero scene:
 *  - Slow-rotating Earth (continents as soft blobs)
 *  - Pulsing solar sun with corona
 *  - Orbiting solar panels
 *  - Spinning wind turbine
 *  - Rising energy rays
 */
export function EarthSunHero() {
  return (
    <div className="relative aspect-square w-full max-w-[520px]">
      {/* Outer orbit ring */}
      <div className="absolute inset-0 rounded-full border border-sky/20" />
      <div className="absolute inset-6 rounded-full border border-leaf/15" />
      <div className="absolute inset-14 rounded-full border border-sun/15 [border-style:dashed]" />

      {/* The Sun — top-right */}
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
        className="absolute right-2 top-2 h-28 w-28 rounded-full animate-sun-pulse"
        style={{
          background:
            "radial-gradient(circle at 35% 35%, oklch(0.95 0.08 90), oklch(0.84 0.18 78) 55%, oklch(0.7 0.2 35) 100%)",
        }}
      />

      {/* Energy rays from sun */}
      <div className="pointer-events-none absolute right-12 top-28">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="absolute h-16 w-[2px] rounded-full bg-gradient-to-t from-transparent via-sun to-transparent animate-ray-rise"
            style={{
              left: i * 8 - 12,
              animationDelay: `${i * 0.7}s`,
            }}
          />
        ))}
      </div>

      {/* The Earth — center, slowly rotating */}
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 1.2, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        className="absolute left-1/2 top-1/2 h-64 w-64 -translate-x-1/2 -translate-y-1/2"
      >
        <div
          className="relative h-full w-full overflow-hidden rounded-full animate-orbit-slow"
          style={{
            background:
              "radial-gradient(circle at 30% 25%, oklch(0.5 0.14 220) 0%, oklch(0.28 0.09 230) 60%, oklch(0.18 0.06 240) 100%)",
            boxShadow:
              "inset -20px -25px 60px oklch(0 0 0 / 0.55), inset 25px 30px 50px oklch(0.85 0.14 78 / 0.18)",
          }}
        >
          {/* Continents as organic blobs */}
          <span
            className="absolute h-20 w-24 rounded-[50%_60%_70%_40%/50%_60%_40%_60%] opacity-90"
            style={{
              top: "18%",
              left: "20%",
              background:
                "radial-gradient(ellipse at 40% 40%, oklch(0.62 0.18 145), oklch(0.5 0.16 150))",
            }}
          />
          <span
            className="absolute h-16 w-14 rounded-[60%_40%_50%_70%/40%_60%_50%_60%] opacity-85"
            style={{
              top: "55%",
              left: "15%",
              background:
                "radial-gradient(ellipse at 50% 50%, oklch(0.55 0.15 140), oklch(0.42 0.13 145))",
            }}
          />
          <span
            className="absolute h-24 w-20 rounded-[55%_45%_60%_50%/60%_50%_50%_60%] opacity-90"
            style={{
              top: "30%",
              right: "10%",
              background:
                "radial-gradient(ellipse at 50% 40%, oklch(0.6 0.17 145), oklch(0.45 0.14 150))",
            }}
          />
          <span
            className="absolute h-12 w-16 rounded-[50%_60%_40%_60%/60%_40%_60%_40%] opacity-80"
            style={{
              bottom: "12%",
              right: "20%",
              background:
                "radial-gradient(ellipse at 50% 50%, oklch(0.58 0.16 140), oklch(0.45 0.13 145))",
            }}
          />

          {/* Atmospheric highlight */}
          <span
            className="absolute inset-0 rounded-full"
            style={{
              background:
                "radial-gradient(circle at 25% 20%, oklch(0.85 0.12 210 / 0.35), transparent 45%)",
            }}
          />
        </div>

        {/* Atmosphere glow */}
        <span
          className="pointer-events-none absolute -inset-2 rounded-full"
          style={{
            boxShadow:
              "0 0 60px 4px oklch(0.78 0.13 210 / 0.35), inset 0 0 30px oklch(0.78 0.13 210 / 0.2)",
          }}
        />
      </motion.div>

      {/* Orbiting solar panel */}
      <div className="absolute inset-0 animate-orbit-medium">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6, duration: 0.8 }}
          className="absolute left-1/2 top-0 -translate-x-1/2"
        >
          <SolarPanelIcon />
        </motion.div>
      </div>

      {/* Orbiting wind turbine (counter-direction feeling via reverse offset) */}
      <div
        className="absolute inset-0 animate-orbit-medium"
        style={{ animationDirection: "reverse", animationDuration: "36s" }}
      >
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.9, duration: 0.8 }}
          className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-2"
        >
          <WindTurbineIcon />
        </motion.div>
      </div>

      {/* Floating leaf */}
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 1.1, duration: 0.8 }}
        className="absolute bottom-10 left-2 animate-leaf-sway"
      >
        <LeafIcon />
      </motion.div>
    </div>
  );
}

function SolarPanelIcon() {
  return (
    <div
      className="relative grid h-8 w-12 grid-cols-3 grid-rows-2 gap-[1.5px] rounded-md p-[2px] shadow-lg shadow-sky/30"
      style={{
        background: "linear-gradient(135deg, oklch(0.4 0.12 220), oklch(0.25 0.08 230))",
        border: "1px solid oklch(0.6 0.13 215 / 0.6)",
      }}
    >
      {Array.from({ length: 6 }).map((_, i) => (
        <span
          key={i}
          className="rounded-[1px]"
          style={{
            background:
              "linear-gradient(135deg, oklch(0.55 0.14 220), oklch(0.3 0.09 230))",
          }}
        />
      ))}
    </div>
  );
}

function WindTurbineIcon() {
  return (
    <div className="relative h-10 w-10">
      {/* Tower */}
      <span className="absolute bottom-0 left-1/2 h-7 w-[2px] -translate-x-1/2 rounded-t-full bg-gradient-to-t from-foreground/60 to-foreground/30" />
      {/* Hub + blades */}
      <div className="absolute left-1/2 top-1 -translate-x-1/2">
        <div className="relative h-4 w-4 animate-spin-blade">
          {[0, 120, 240].map((rot) => (
            <span
              key={rot}
              className="absolute left-1/2 top-1/2 h-[10px] w-[2px] origin-bottom -translate-x-1/2 -translate-y-full rounded-full bg-foreground/85"
              style={{ transform: `translate(-50%, -100%) rotate(${rot}deg)` }}
            />
          ))}
          <span className="absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-sun" />
        </div>
      </div>
    </div>
  );
}

function LeafIcon() {
  return (
    <svg
      width="36"
      height="36"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M3 21c0-9 7-15 18-15-1 9-7 15-15 15-1 0-2-.4-3-1z"
        fill="oklch(0.6 0.16 145)"
        stroke="oklch(0.78 0.18 145)"
        strokeWidth="0.6"
      />
      <path
        d="M5 19c4-5 8-8 14-10"
        stroke="oklch(0.85 0.16 145)"
        strokeWidth="0.8"
        strokeLinecap="round"
      />
    </svg>
  );
}