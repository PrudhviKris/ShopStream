import { useEffect, useState } from "react";
import { api } from "../api";

const when = (iso) => new Date(iso + "Z").toLocaleDateString();

/** Read-only star row. `value` may be fractional (e.g. 4.5) for an average. */
export function StarRating({ value, size = 16 }) {
  const rounded = Math.round((value || 0) * 2) / 2; // nearest half star
  return (
    <span className="stars" style={{ fontSize: size }} title={value ? `${value} out of 5` : "No ratings yet"}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={`star ${rounded >= n ? "full" : rounded >= n - 0.5 ? "half" : ""}`}>★</span>
      ))}
    </span>
  );
}

/** Compact rating summary for the product card — average + review count. */
export function RatingSummary({ product }) {
  if (!product.review_count) return <span className="sub rating-empty">No reviews yet</span>;
  return (
    <span className="rating-summary">
      <StarRating value={product.average_rating} size={13} />
      <span className="sub">{product.average_rating} ({product.review_count})</span>
    </span>
  );
}

/** Pick a star by clicking — used in the write-a-review form. */
function StarPicker({ value, onChange }) {
  return (
    <span className="stars picker" style={{ fontSize: 26 }}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span
          key={n}
          className={`star ${value >= n ? "full" : ""}`}
          onClick={() => onChange(n)}
          role="button"
          aria-label={`${n} star${n === 1 ? "" : "s"}`}
        >
          ★
        </span>
      ))}
    </span>
  );
}

function WriteReview({ productId, existing, onSubmitted, notify }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!rating) return;
    setBusy(true);
    try {
      await api.createReview(productId, rating, comment);
      notify("Review submitted", "Thanks — it'll appear here once our team approves it.");
      onSubmitted();
    } catch (err) {
      notify("Couldn't submit your review", err.message);
    } finally {
      setBusy(false);
    }
  }

  if (existing) {
    return (
      <div className="review-mine">
        <p className="eyebrow">YOUR REVIEW</p>
        <StarRating value={existing.rating} />
        {existing.comment && <p className="sub">“{existing.comment}”</p>}
        <span className={`badge review-${existing.status}`}>
          {existing.status === "pending" ? "awaiting approval" : existing.status}
        </span>
      </div>
    );
  }

  return (
    <form className="review-form" onSubmit={submit}>
      <p className="eyebrow">WRITE A REVIEW</p>
      <StarPicker value={rating} onChange={setRating} />
      <textarea
        rows={2}
        maxLength={2000}
        placeholder="How did it work out for you? (optional)"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <button className="btn btn-outline btn-sm" disabled={busy || !rating}>
        {busy ? "Submitting…" : "Submit review"}
      </button>
    </form>
  );
}

/** Full reviews section for the product detail modal: aggregate, write form
 * (gated by eligibility), and the review list with a recent/top toggle. */
export function ReviewsSection({ product, user, notify }) {
  const [sort, setSort] = useState("recent");
  const [data, setData] = useState(null);
  const [eligibility, setEligibility] = useState(null);

  const loadReviews = () => api.productReviews(product.id, sort).then(setData).catch(() => {});
  const loadEligibility = () => {
    if (!user) return setEligibility(null);
    api.myReviewEligibility(product.id).then(setEligibility).catch(() => {});
  };

  useEffect(() => { loadReviews(); }, [product.id, sort]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { loadEligibility(); }, [product.id, user]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="reviews-section">
      <div className="reviews-head">
        <h3>Reviews</h3>
        {data && data.total_reviews > 0 && (
          <span className="rating-summary">
            <StarRating value={data.average_rating} />
            <span className="sub">{data.average_rating} average · {data.total_reviews} review{data.total_reviews === 1 ? "" : "s"}</span>
          </span>
        )}
      </div>

      {user ? (
        eligibility === null ? null : eligibility.can_review ? (
          <WriteReview
            productId={product.id}
            notify={notify}
            onSubmitted={() => { loadEligibility(); loadReviews(); }}
          />
        ) : eligibility.review ? (
          <WriteReview productId={product.id} existing={eligibility.review} notify={notify} onSubmitted={() => {}} />
        ) : (
          <p className="sub-note">{eligibility.reason}</p>
        )
      ) : (
        <p className="sub-note">Sign in to write a review once you've received this product.</p>
      )}

      {data && data.total_reviews > 0 && (
        <>
          <div className="chip-row" role="group" aria-label="Sort reviews">
            <button className={`chip ${sort === "recent" ? "on" : ""}`} onClick={() => setSort("recent")}>Most recent</button>
            <button className={`chip ${sort === "top" ? "on" : ""}`} onClick={() => setSort("top")}>Top rated</button>
          </div>
          <ul className="review-list">
            {data.items.map((r) => (
              <li key={r.id} className="review-item">
                <div className="review-item-head">
                  <StarRating value={r.rating} size={13} />
                  <strong>{r.user_name || "Customer"}</strong>
                  <span className="sub">{when(r.created_at)}</span>
                </div>
                {r.comment && <p>{r.comment}</p>}
              </li>
            ))}
          </ul>
        </>
      )}
      {data && data.total_reviews === 0 && <p className="sub-note">No reviews yet — be the first.</p>}
    </div>
  );
}
