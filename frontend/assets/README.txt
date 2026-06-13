Drop the two design images here (the UI references them exactly as built):

  eye-logo.png   — the glowing Kirlian "eye" mark (the header wordmark + EyeMark atom)
  aura.webp      — the Kirlian aura/star backdrop behind the hero headline

These are the images from the CLIPMAKER.AI mockup. They are served at
/assets/eye-logo.png and /assets/aura.webp by the FastAPI static mount, which is
what theme.jsx (EyeMark) and dirB.jsx (hero <img src="assets/aura.webp">) load.

Until you add them the layout is intact — the wordmark text and aura simply render
without the imagery (the <img> alt is empty, so no broken-image text appears).
