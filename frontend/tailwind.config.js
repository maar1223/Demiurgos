/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        cripta: "#0A0907",
        madero: "#161310",
        piedra: "#1F1B16",
        lecho: "#211D17",
        pergamino: "#DED5C7",
        "tinta-desvaida": "#A6988A",
        sombra: "#73685E",
        filio: "#3A3229",
        llamita: "#D4A853",
        "llama-alta": "#F5C95A",
        plata: "#8A9BA8",
        "plata-tenue": "#6D7D88",
        musgo: "#4A6B3E",
        sangre: "#8B2D24",
      },
      fontFamily: {
        heading: ["Space Grotesk", "sans-serif"],
        body: ["Inter", "sans-serif"],
      },
      fontSize: {
        display: ["3rem", { lineHeight: "1.1", fontWeight: "700" }],
        h1: ["2.5rem", { lineHeight: "1.2", fontWeight: "700" }],
        h2: ["2rem", { lineHeight: "1.3", fontWeight: "600" }],
        h3: ["1.5rem", { lineHeight: "1.4", fontWeight: "600" }],
        h4: ["1.25rem", { lineHeight: "1.4", fontWeight: "600" }],
        body: ["1rem", { lineHeight: "1.6", fontWeight: "400" }],
        small: ["0.875rem", { lineHeight: "1.5", fontWeight: "400" }],
        xs: ["0.75rem", { lineHeight: "1.4", fontWeight: "400" }],
      },
      screens: {
        mobile: { max: "767px" },
        tablet: { min: "768px", max: "1199px" },
        desktop: "1200px",
      },
    },
  },
  plugins: [require("@tailwindcss/typography")],
};
