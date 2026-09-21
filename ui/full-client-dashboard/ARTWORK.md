# Decorative website artwork

The release reuses four original AI-generated fan illustrations from the user-approved MapleBench website design. They were generated on September 12, 2026 with the built-in image tool. PNGs are copied byte for byte with provenance metadata intact. They are not extracted game assets, screenshots or benchmark evidence. No official affiliation is claimed. The exact generation and cleanup prompts are retained below.

The leaf and skill book use white backgrounds blended into the light page; the companion image uses transparency. The village fills a decorative, noninteractive layer behind opaque content panels. Font licensing is in OFL-Manrope.txt.

## maple-companions.png

Create one small website decoration: a friendly orange mushroom monster and a glossy green slime standing close together, inspired by the nostalgic 2000s MapleStory visual world. This is original fan illustration for a clean independent research website, not a logo, not an official asset. Style: beautifully crafted 2D pixel art sprite vignette, crisp stepped pixel edges, warm dark-brown outlines, soft warm cream mushroom stem with two tiny black eyes, big orange cap with cream spots, rounded lime-green slime with two small eyes and a little sprout on top, tiny grounded pixel shadows only. Composition: landscape 3:2 transparent canvas; the two creatures form one compact group, mushroom on the left slightly taller, slime on the right, baseline aligned, both fully visible with no crop. Fill most of the canvas with the two creatures and minimal clear padding. No environment, no ground platform, no grass, no text, no letters, no watermark, no UI, no extra objects. Genuine transparent alpha background. This will display at 110 by 74 pixels on a white page; prioritize clear silhouettes, simple adorable faces, and sharp details readable at that size. Output as a PNG with transparency.

## henesys-world.png

Use case: stylized-concept. Asset: a full-bleed background for a website whose opaque white content cards sit in the middle. Create an original nostalgic early-2000s MapleStory / Henesys-inspired village landscape. The attached image is a style and architecture reference only; expand the feeling into an entire world rather than keeping its white background. Landscape canvas, 3:2 aspect ratio. Fill every pixel with scenery: soft pale-blue sky, a few creamy clouds, distant green hills, lush grassy platforms with rounded stone edges, small daisies and ferns, a warm yellow mushroom-roof cottage on the far left and an orange mushroom-roof cottage on the far right, welcoming wooden doors, short fences and little wooden ladders. Tall friendly leafy trees frame both outer edges and upper corners. The central 60 percent should be simpler open sky and meadow because webpage cards cover it; concentrate the charming cottages, trees and platform detail in the outer 20 percent on each side. Beautiful hand-crafted 2D pixel art with visible crisp stepped edges, warm brown outlines, gently shaded foliage and a coherent soft sage / mint / pale blue / warm yellow palette. Moderately saturated and cheerful, clear enough to recognize as a game environment, never dark or neon. No characters, no interface, no letters, no signs with text, no watermark, no rectangular borders, no white empty background, no transparency. This is original independent fan art, not a screenshot or copied official game asset. Output PNG.

## maple-leaf.png — generation

Create one original website decoration inspired by nostalgic early-2000s MapleStory inventory artwork. Match the attached mushroom-and-slime reference's charming pixel-art rendering, warm dark-brown stepped outlines, warm cream highlights, rich saturated color, and restrained shading. The attached image is a style reference only; do not include its creatures. Crisp chunky pixels and a very clear silhouette, readable as a 48–64 px web icon. Single compact subject centered on a square canvas, filling approximately 85% of the width and height with narrow transparent padding. Genuine transparent alpha background, no backdrop, no environment, no panel, no text, no letters, no watermark, no cast glow outside the object. Original fan artwork, not an official asset. Output PNG. Subject: a beautiful five-lobed orange-red maple leaf, unmistakable maple silhouette, little golden highlights along the upper edges and gently darker red at the tips, subtle warm amber veins, a short curved brown stem descending down and right. The leaf points upward and tilts a little to the left. Make it feel like a treasured colorful inventory item. No face, no eyes, no extra objects.

## maple-leaf.png — cleanup

Edit the attached maple-leaf artwork. Preserve the orange leaf and its pixel-art style exactly. Remove the entire gray-and-white checkerboard pattern behind and between the leaf's lobes. Replace the checkerboard with a completely solid pure white (#FFFFFF) background. The checkerboard is mistakenly painted into this image and must disappear completely. No gray grid, no pattern, no shadow, no off-white texture. Keep the leaf's silhouette intact and its colors vivid. Retain the square canvas and its narrow margins. Output PNG.

## skill-book.png

Use case: stylized-concept. Create one original decorative fan-art sprite for a clean independent MapleStory research website. Use the attached mushroom-and-slime image ONLY as the style reference: charming chunky 2D pixel art, warm dark-brown stepped outlines, cream pixel highlights, adorable small facial features, saturated but warm colors. Do not include the reference creatures. Square canvas, one compact isolated subject centered, filling 85% of the canvas with narrow padding. Keep the silhouette simple and readable when displayed at 50 pixels. Solid pure white #FFFFFF background, no transparency checkerboard, no shadow or glow outside the silhouette, no text, no watermark, no UI, no panels. Original artwork rather than a copied official game sprite. Output PNG. Subject: a small treasured adventurer's skill book, closed, warm forest-green cover, thick cream parchment pages, gold corner protectors, little red ribbon bookmark, and one simple golden maple-leaf emblem on the cover. A softly rounded thick book seen in three-quarter view so its pages and cover are visible. No lettering or numbers, no face.

## Section Art

# Section art generation record


## Section companions and Henesys-inspired scenery

Generated with the built-in image tool on September 12, 2026, using the existing `maple-companions.png` only as a style reference. These are original website fan illustrations, not extracted game assets. The source PNGs are copied intact with their generation provenance. The new files use white backgrounds and CSS multiply blending; the scenery is muted in CSS rather than baked into the image.

| File | Placement | Original dimensions |
| --- | --- | --- |
| `blue-snail.png` | Architecture heading | 1254 × 1254 |
| `ribbon-pig.png` | Recordings heading | 1254 × 1254 |
| `little-stump.png` | Attempt history accordion | 1254 × 1254 |
| `skill-book.png` | Methodology heading | 1254 × 1254 |
| `henesys-garden.png` | Faint scenery behind the introduction and footer | 2172 × 724 |

The existing meso pouch marks Results, and the scroll remains with the introductory quest. Thus each main content section includes an illustration. All new section illustrations are decorative and load lazily. Scenery is noninteractive, uses no animation, and is kept behind readable content. The town interpretation draws on the mushroom cottages, grassy ledges and treehouse scenery shown in [MapleStory’s own Henesys memory-lane post](https://x.com/MapleStory/status/1174058449090621441); no artwork from that post was copied into this project.

The growing collection should be served as cacheable static artwork when ported to the live site, rather than embedded wholesale into the size-limited audited HTML payload. This reference snapshot remains separate from the current live results.

### Exact section-art prompts

#### blue-snail.png

Use case: stylized-concept. Create one original decorative fan-art sprite for a clean independent MapleStory research website. Use the attached mushroom-and-slime image ONLY as the style reference: charming chunky 2D pixel art, warm dark-brown stepped outlines, cream pixel highlights, adorable small facial features, saturated but warm colors. Do not include the reference creatures. Square canvas, one compact isolated subject centered, filling 85% of the canvas with narrow padding. Keep the silhouette simple and readable when displayed at 50 pixels. Solid pure white #FFFFFF background, no transparency checkerboard, no shadow or glow outside the silhouette, no text, no watermark, no UI, no panels. Original artwork rather than a copied official game sprite. Output PNG. Subject: a tiny friendly MapleStory-inspired blue snail crawling toward the right. Large round cobalt-blue spiral shell, soft cream-yellow body, two little upright eye stalks and a tiny smile, cheerful inquisitive expression. No ground or grass.

#### ribbon-pig.png

Use case: stylized-concept. Create one original decorative fan-art sprite for a clean independent MapleStory research website. Use the attached mushroom-and-slime image ONLY as the style reference: charming chunky 2D pixel art, warm dark-brown stepped outlines, cream pixel highlights, adorable small facial features, saturated but warm colors. Do not include the reference creatures. Square canvas, one compact isolated subject centered, filling 85% of the canvas with narrow padding. Keep the silhouette simple and readable when displayed at 50 pixels. Solid pure white #FFFFFF background, no transparency checkerboard, no shadow or glow outside the silhouette, no text, no watermark, no UI, no panels. Original artwork rather than a copied official game sprite. Output PNG. Subject: a chubby friendly pale pink pig with a large bright red bow tied just behind its ears, inspired by the classic ribbon pigs around Henesys. Facing three-quarter right, four tiny feet, round snout with two nostrils, little black eyes, curled tail. Keep the bow visibly red, the body round and pink, and the expression sweet.

#### little-stump.png

Use case: stylized-concept. Create one original decorative fan-art sprite for a clean independent MapleStory research website. Use the attached mushroom-and-slime image ONLY as the style reference: charming chunky 2D pixel art, warm dark-brown stepped outlines, cream pixel highlights, adorable small facial features, saturated but warm colors. Do not include the reference creatures. Square canvas, one compact isolated subject centered, filling 85% of the canvas with narrow padding. Keep the silhouette simple and readable when displayed at 50 pixels. Solid pure white #FFFFFF background, no transparency checkerboard, no shadow or glow outside the silhouette, no text, no watermark, no UI, no panels. Original artwork rather than a copied official game sprite. Output PNG. Subject: a tiny friendly walking tree stump inspired by the classic MapleStory beginner monsters. Short round brown stump body with a pale cut-wood top showing just two tree rings, two small branch arms, two little root feet, small black oval eyes, mild sleepy expression, one little green leaf sprouting from a twig. Natural warm tan and cocoa bark, no accessories.

#### skill-book.png

Use case: stylized-concept. Create one original decorative fan-art sprite for a clean independent MapleStory research website. Use the attached mushroom-and-slime image ONLY as the style reference: charming chunky 2D pixel art, warm dark-brown stepped outlines, cream pixel highlights, adorable small facial features, saturated but warm colors. Do not include the reference creatures. Square canvas, one compact isolated subject centered, filling 85% of the canvas with narrow padding. Keep the silhouette simple and readable when displayed at 50 pixels. Solid pure white #FFFFFF background, no transparency checkerboard, no shadow or glow outside the silhouette, no text, no watermark, no UI, no panels. Original artwork rather than a copied official game sprite. Output PNG. Subject: a small treasured adventurer's skill book, closed, warm forest-green cover, thick cream parchment pages, gold corner protectors, little red ribbon bookmark, and one simple golden maple-leaf emblem on the cover. A softly rounded thick book seen in three-quarter view so its pages and cover are visible. No lettering or numbers, no face.

#### henesys-garden.png

Use case: stylized-concept. Create an original nostalgic pixel-art landscape decoration for the background of a clean MapleStory research website, inspired by old Henesys. Use the attached image only as a style reference for warm charming 2D pixel edges, not as subject matter. Very wide landscape canvas, 3:1 aspect ratio. A low strip of soft green grass and tiny white daisies runs along the bottom fifth of the image. On the far left, one small whimsical cottage with a warm yellow spotted mushroom roof, cream walls and a round wooden door, a short wooden fence and a low rounded bush. On the far right, a slightly smaller orange mushroom-roofed cottage nestled under a small leafy tree, with a tiny wooden ladder nearby. The central half of the canvas is almost entirely empty pure white, with only a few low grass tufts at the bottom: this must leave calm negative space for website content. All scenery stays in the bottom half; upper half is completely pure white. Muted but recognizable sage green, pale yellow and warm orange, low contrast, delicate brown outlines. No characters, no UI, no labels, no text, no watermark, no sky color, no mountain wall. Do not draw a hard horizontal rectangular ground edge; the grassy silhouette tapers into pure white around its ends and bottom. This is a light decorative vignette, not a dense full game screenshot. Solid pure white #FFFFFF background; do not depict a transparency grid. Output PNG.

### Snail correction prompt

The initial snail had extra eyes on its body. Only the corrected final render is included.

Edit this blue snail sprite with one precise correction: it must have exactly TWO eyes total, one at the tip of each of its two upright stalks. Remove the two extra dark oval eyes from the lower cream-colored face/body, filling those spots with matching smooth cream-yellow pixel shading. Keep the small smiling mouth and pink cheeks on the lower face. Preserve the blue spiral shell, two eye stalks and their eyes, outlines, pose, white background, canvas dimensions, and all other artwork exactly. No extra eyes or other changes.

## World Background

# Full-world background and section-card layout

The new `henesys-world.png` is an original fan-art background generated with the built-in image tool on September 12, 2026. Its style reference was the earlier `henesys-garden.png`, which is also original generated website artwork. The final 1536 × 1024 PNG was copied intact with its provenance metadata. No extracted game assets or third-party screenshots were added.

The image fills a fixed decorative layer behind the entire page. Opaque paper cards provide readable sections over the scenery. It has no animation, cannot intercept pointer events, and is hidden from assistive technology. Supporting technical notes and detailed evidence remain available in disclosures; the underlying result data is unchanged.

## Exact generation prompt

Use case: stylized-concept. Asset: a full-bleed background for a website whose opaque white content cards sit in the middle. Create an original nostalgic early-2000s MapleStory / Henesys-inspired village landscape. The attached image is a style and architecture reference only; expand the feeling into an entire world rather than keeping its white background. Landscape canvas, 3:2 aspect ratio. Fill every pixel with scenery: soft pale-blue sky, a few creamy clouds, distant green hills, lush grassy platforms with rounded stone edges, small daisies and ferns, a warm yellow mushroom-roof cottage on the far left and an orange mushroom-roof cottage on the far right, welcoming wooden doors, short fences and little wooden ladders. Tall friendly leafy trees frame both outer edges and upper corners. The central 60 percent should be simpler open sky and meadow because webpage cards cover it; concentrate the charming cottages, trees and platform detail in the outer 20 percent on each side. Beautiful hand-crafted 2D pixel art with visible crisp stepped edges, warm brown outlines, gently shaded foliage and a coherent soft sage / mint / pale blue / warm yellow palette. Moderately saturated and cheerful, clear enough to recognize as a game environment, never dark or neon. No characters, no interface, no letters, no signs with text, no watermark, no rectangular borders, no white empty background, no transparency. This is original independent fan art, not a screenshot or copied official game asset. Output PNG.
