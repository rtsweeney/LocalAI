# 08. The news desk

`newsdesk\newsdesk.py` is your local model's first pass at entries for the **Latest** list on your news site. It reads feeds, finds stories that more than one outlet is covering, drafts an entry for each in the site's own format, checks its own work, and hands you a page to review.

**Nothing it writes is published.** Drafts are files on your PC until you approve them.

## The rules it follows

These come straight from your site's plan (`the_news`, `planning/08-home-ai-node.md`):

| Rule from the plan | How the tool does it |
|---|---|
| A fixed workflow, not a free-roaming agent | The code decides every step. The model answers one narrow question per story and has no tools. |
| Closed book | The model sees only the article text fetched in that run. |
| Quote or it didn't happen | The model must give exact quotes as evidence. The code checks each quote is really in the article it names. |
| Numbers and names check | Every number and every capitalized word in a draft must appear in the fetched articles. |
| Forced output format, then validation | Ollama is told to answer in a fixed JSON shape, and the code validates it anyway, retries once, then flags it. |
| Deterministic settings | Temperature 0. |
| Stamp who produced it | Each draft records the exact model file and prompt version. |
| Every draft goes through you | Nothing leaves the drafts folder until you list its id in `approved.txt`. |

It also applies the site's build rules (`tools/build.mjs`): at least two sources from different sites, `https` links, a title of 120 characters or less, and a topic from the site's list.

## Run it

```powershell
python newsdesk\newsdesk.py run
```

You will see four stages:

```
1/4 Reading feeds
2/4 Grouping 61 headlines into stories
3/4 Drafting
  Story 1: Senate passes spending bill ...
    checks_passed
  Story 2: Appeals court ...
    needs_attention
      - Numbers not found in any article: 3
4/4 Writing the review page
```

Then open the `review.html` file it names. Each draft is a card:

- **Green, "Checks passed":** the quotes, numbers and names were all found in the articles.
- **Orange, "Needs attention":** something wasn't. The card lists exactly what.

**Passing the checks is not the same as being right.** The checks prove the model didn't invent a number or a name. They can't tell whether the summary is fair, complete, or about the most important part of the story. Read the sources before approving.

Every card also asks you to confirm two things the tool can't know:

1. **The date.** It uses the day the first article was published, which isn't always the day the event happened.
2. **A primary source.** It only has news articles. Add the court filing, bill text or official statement if one exists.

## Approve and export

1. In the same folder as `review.html`, open `approved.txt`.
2. Add the id of each draft you approve, one per line. The id is at the bottom of each card.
3. To change wording, edit the draft's `.json` file first. You are the editor.
4. Run:
   ```powershell
   python newsdesk\newsdesk.py export
   ```

This writes `recent-local-DATE.json`, in the same shape as the researchers' files in your site repo (`recent-a.json` and the others).

## Getting approved entries onto the site

**This last step is not automated yet.** Your site builds `site/recent.js` from a fixed list of four files, so a new file isn't picked up until the site's `build.mjs` is told about it. That change belongs in the `the_news` repo, and it was left alone because this kit only had read access to it.

Until then, by hand:

1. Copy the exported file into `planning/research/2026-10-22-recent/` in `the_news`.
2. Add its name to the two file lists in that folder's `build.mjs`, and update the `checked` date there.
3. Run `node build.mjs`, then `npm run build` to run the site's checks.
4. Commit to a **new branch** and open a pull request. Netlify gives you a preview link. Merge when it looks right.

Going through a pull request means a mistake shows up on a preview, never on the live site.

## Settings

Everything is in `newsdesk\config.json`:

| Setting | What it does | Default |
|---|---|---|
| `feeds` | The RSS feeds to read. Add or remove outlets here. | Five outlets |
| `chat_model` | The model that drafts | `gemma4:12b` |
| `min_outlets` | How many different outlets must cover a story | 2 |
| `max_stories` | Drafts per run | 8 |
| `look_back_hours` | How far back to look | 36 |
| `same_story_similarity` | How alike two headlines must be to count as one story, from 0 to 1 | 0.75 |

**Tuning `same_story_similarity`.** If unrelated stories get merged, raise it (try 0.8). If the same story appears as separate drafts, or you get "0 stories", lower it (try 0.65). The right value depends on the embedding model, and 0.75 is a starting guess that hasn't been tuned on a real model.

**About the feeds.** The five starter feeds all answered on Nov. 14, 2026. They are not balanced across the political spectrum the way your site's ten-outlet panel is; replace them with your panel's feeds. Some sites block automated readers: The Hill's articles refused the test server. Those are skipped with a note, and may work from your home connection.

## Running it every morning

In AI Home, open the **Schedule** tab and add a job:

- **What it does:** Run the news desk
- **When:** `daily at 5am`

When drafts are ready, a banner on the Home tab links straight to the review page. The PC must be awake, with Ollama and AI Home running, at that time ([10](10-control-panel.md#keeping-schedules-alive)).

## What has and hasn't been tested

- **Tested with a pretend model:** the whole flow, including a model that invents a number and a name (caught), a story only one outlet covers (never drafted), an off-topic story (dropped), a web page that tries to give the model orders (never reaches it), and export. Run `python -m unittest discover tests` to see for yourself.
- **Tested on real sites:** reading the five feeds and extracting article text.
- **Not tested:** a real model. How good `gemma4:12b`'s drafts are, and how often they pass, is something only your machine can show. Your plan's "bake-off" (the same articles through several models) is the right way to pick one.

## Known limits

- The names check works on capitalized words, so it won't notice a wrong lowercase word, and it can't tell that a real name was attached to the wrong action.
- Numbers written as words ("three") are not checked.
- It drafts only **Latest** entries. Rating coverage and storylines follow your guidelines' full process and are not touched.
- Pages that need JavaScript or a subscription can't be read and are skipped.

---

Next: [09. Troubleshooting](09-troubleshooting.md)
