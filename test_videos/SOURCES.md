# Test video sources (Mixkit, free license)

Downloaded as 720p H.264 from Mixkit CDN. Replace any clip if Frigate/vision mis-labels it.

| file | clip | page |
| --- | --- | --- |
| `empty.mp4` | Empty office space | https://mixkit.co/free-stock-video/empty-office-space-15478/ |
| `intruder.mp4` | Thief creep through house and looks up at camera | https://mixkit.co/free-stock-video/thief-creep-through-house-and-looks-up-at-camera-12830/ |
| `forced_entry.mp4` | Mugger opening the lock at night | https://mixkit.co/free-stock-video/mugger-opening-the-lock-at-night-31380/ |
| `loitering.mp4` | Bored man waits for girlfriend shopping clothes | https://mixkit.co/free-stock-video/bored-man-waits-for-girlfriend-shopping-clothes-12943/ |
| `pet.mp4` | Kitten walking alone | https://mixkit.co/free-stock-video/kitten-walking-alone-26370/ |

Note: Google doesn’t host direct free downloads for these cases; Mixkit is royalty-free and Frigate-friendly (H.264 1280×720).

## Known limitation: `forced_entry.mp4`

This clip is **excluded from `expected.csv`** on purpose.

Frigate is configured with `objects.track: [person]`. The clip is framed as an
extreme close-up — two hands, a tool and a lock, with only a sliver of a masked
head at the edge. There is no person-shaped object for the detector to find, so
Frigate opens no review, publishes no MQTT message, and the brain never runs.

This was verified in isolation on a clean slate (no open review, single clip):
Frigate logged **zero events and zero reviews** for the whole 40s publish.

It is worth being precise about where the limit is, because it is *not* the
vision model. Handed the same frame directly, Gemini classifies it correctly
and with a good description:

> `forced_entry` / high — "A person wearing a black mask and jacket attempts to
> pick the lock of a metal door using tools and a flashlight."

So the ceiling is the object detector's framing sensitivity, not the reasoning
layer. A wider shot showing a full body at the door would flow through the
pipeline normally. The clip is kept in the repo as a reference case for that
boundary.
