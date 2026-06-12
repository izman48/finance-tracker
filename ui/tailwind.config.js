/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        display: ['"Space Grotesk"', 'Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        ink: {
          950: '#070A13',
          900: '#0A0F1C',
          800: '#101729',
          700: '#16203A',
        },
        card: '#0F1626',
        card2: '#141D33',
        accent: {
          DEFAULT: '#2DD4A7',
          bright: '#4AE3BB',
          dim: '#1A8A6C',
        },
        pos: '#34D399',
        neg: '#FB7185',
        warn: '#FBBF24',
        sky2: '#38BDF8',
        viol: '#A78BFA',
      },
      boxShadow: {
        card: '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 8px 24px -12px rgba(0,0,0,0.5)',
        pop: '0 12px 40px -8px rgba(0,0,0,0.65)',
        glow: '0 0 60px -12px rgba(45, 212, 167, 0.35)',
      },
      animation: {
        'float-slow': 'float 14s ease-in-out infinite',
        'float-slower': 'float 20s ease-in-out infinite reverse',
        'fade-up': 'fadeUp 0.5s ease both',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)' },
          '50%': { transform: 'translate3d(4%, -6%, 0) scale(1.08)' },
        },
        fadeUp: {
          from: { opacity: '0', transform: 'translateY(14px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
