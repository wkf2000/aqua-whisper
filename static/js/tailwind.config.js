// Tailwind Play CDN theme, shared by both pages. Loaded after the CDN script.
window.tailwind.config = {
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'system-ui', 'sans-serif'] },
      colors: {
        surface: '#1E293B',
        bg: '#0F172A',
        accent: '#22C55E',
        muted: '#94A3B8',
      },
    },
  },
};
