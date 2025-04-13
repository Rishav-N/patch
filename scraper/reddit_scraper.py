import praw
import requests
import os

reddit = praw.Reddit(
    client_id="L__B0xUG71WhO6ec7ocmXQ",   # YOUR client_id
    client_secret="O5ngYRTxBrPMSWD1XDl4TQb-aQXyDg",  # YOUR client_secret
    user_agent="pest-scraper-script by u/Character_Shoe_9475"
)
search_terms = [
    "pests",
    "pest",
    "bug",
    "bugs",
    "rat",
    "rats",
    "mouse",
    "mice",
    "insect",
    "insects",
    "infestation",
    "cockroach",
    "roach"
]

os.makedirs("pests", exist_ok=True)

count = 0
subreddits = "pests+pestcontrol+HomeImprovement+homeowners+Home+UrbanHell+Plumbing"
for term in search_terms:
    for submission in reddit.subreddit(subreddits).search(term, limit=500):
        if submission.url.endswith(('.jpg', '.jpeg', '.png')):
            print(f"Downloading: {submission.url}")
            img_data = requests.get(submission.url).content
            with open(f"pests/{count}.jpg", "wb") as f:
                f.write(img_data)
            count += 1

print(f"Downloaded {count} images.")
