# Teaching Notes

- The user's goal is package maintenance, not general interpreter usage.
- Teach runtime concepts through their consequences for `deepagents-monty`.
- Underlying Monty behavior is important when it affects lifecycle, state,
  callbacks, isolation, limits, or failure recovery.
- Vibebin publishes a single isolated HTML file. Keep shared assets in source,
  but produce a self-contained publish build with CSS embedded and all links
  made absolute before running `vibebin publish`.
