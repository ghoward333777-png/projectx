"""QueryBook — one shared FQL knowledge base behind four domain apps.

The Language, STEM, History and Video-generation apps stay separate (each can
run on its own port or inside the hub), but all of them read and write the same
FQL document store and see the same real-time change feed.
"""

__version__ = "0.1.0"
