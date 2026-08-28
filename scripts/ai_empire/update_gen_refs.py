# Quick patch to the gen script to document reference usage
# (full integration would load the ref images for img2img in the generator)

import re
with open("/home/ubuntu/ai-empire-blueprint/plans/jordan_influencer_gen.py") as f:
    content = f.read()

# Add note after the locked prompt section
note = 
