from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

model = SentenceTransformer("all-MiniLM-L6-v2")

def deduplicate(articles, threshold=0.82):
    if not articles:
        return []
    texts = [a["title"] + " " + a["summary"] for a in articles]
    embeddings = model.encode(texts)
    sim_matrix = cosine_similarity(embeddings)

    visited = set()
    merged  = []

    for i in range(len(articles)):
        if i in visited:
            continue
        cluster = [i]
        for j in range(i+1, len(articles)):
            if j not in visited and sim_matrix[i][j] >= threshold:
                cluster.append(j)
                visited.add(j)
        visited.add(i)

        best = articles[cluster[0]]
        best["sources"] = [articles[k]["url"] for k in cluster]
        merged.append(best)

    print(f"After dedup: {len(merged)} unique stories")
    return merged