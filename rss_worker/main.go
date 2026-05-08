package main

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/joho/godotenv"
)

const (
	defaultDjangoBaseURL     = "http://127.0.0.1:8000"
	feedsEndpoint            = "/api/feeds/"
	feedStatusEndpointFmt    = "/api/feeds/%d/fetch-status/"
	ingestEndpoint           = "/api/articles/ingest/"
	defaultHTTPTimeoutSec    = 15
	defaultMaxConcurrency    = 8
	defaultIngestRetryCount  = 3
	defaultInitialBackoffSec = 1
)

type workerConfig struct {
	DjangoBaseURL  string
	HTTPTimeout    time.Duration
	MaxConcurrency int
	IngestMaxRetry int
	InitialBackoff time.Duration
	APIToken       string
}

type Feed struct {
	ID           int    `json:"id"`
	Name         string `json:"name"`
	URL          string `json:"url"`
	Category     string `json:"category,omitempty"`
	ETag         string `json:"etag,omitempty"`
	LastModified string `json:"last_modified,omitempty"`
}

type IngestArticle struct {
	FeedID      *int    `json:"feed_id,omitempty"`
	Title       string  `json:"title"`
	Link        string  `json:"link"`
	GUID        string  `json:"guid,omitempty"`
	Summary     string  `json:"summary,omitempty"`
	Content     string  `json:"content,omitempty"`
	ImageURL    string  `json:"image_url,omitempty"`
	PublishedAt *string `json:"published_at,omitempty"`
}

type ingestResponse struct {
	OK       bool `json:"ok"`
	Received int  `json:"received"`
	Created  int  `json:"created"`
	Skipped  int  `json:"skipped"`
}

type rssDocument struct {
	Channel rssChannel `xml:"channel"`
}

type rssChannel struct {
	Items []rssItem `xml:"item"`
}

type rssItem struct {
	Title          string         `xml:"title"`
	Link           string         `xml:"link"`
	GUID           string         `xml:"guid"`
	Description    string         `xml:"description"`
	Content        string         `xml:"http://purl.org/rss/1.0/modules/content/ encoded"`
	PubDate        string         `xml:"pubDate"`
	MediaThumbnail mediaURL       `xml:"http://search.yahoo.com/mrss/ thumbnail"`
	MediaContent   []mediaContent `xml:"http://search.yahoo.com/mrss/ content"`
	Enclosure      enclosure      `xml:"enclosure"`
}

type atomFeed struct {
	Entries []atomEntry `xml:"entry"`
}

type atomEntry struct {
	Title   string     `xml:"title"`
	Links   []atomLink `xml:"link"`
	ID      string     `xml:"id"`
	Summary string     `xml:"summary"`
	Content string     `xml:"content"`
	Updated string     `xml:"updated"`
	Published string   `xml:"published"`
}

type atomLink struct {
	Href string `xml:"href,attr"`
	Rel  string `xml:"rel,attr"`
	Type string `xml:"type,attr"`
}

type mediaURL struct {
	URL string `xml:"url,attr"`
}

type mediaContent struct {
	URL    string `xml:"url,attr"`
	Medium string `xml:"medium,attr"`
	Type   string `xml:"type,attr"`
}

type enclosure struct {
	URL  string `xml:"url,attr"`
	Type string `xml:"type,attr"`
}

var imgSrcRe = regexp.MustCompile(`<img[^>]+src=["']([^"']+)["']`)

type feedFetchResult struct {
	FeedID       int
	FeedName     string
	FeedURL      string
	Articles     []IngestArticle
	Err          error
	HTTPCode     int
	FetchedAt    time.Time
	NotModified  bool
	ETag         string
	LastModified string
	ItemCount    int
}

type feedStatusPayload struct {
	Status       string `json:"status"`
	HTTPStatus   int    `json:"http_status,omitempty"`
	Error        string `json:"error,omitempty"`
	ETag         string `json:"etag,omitempty"`
	LastModified string `json:"last_modified,omitempty"`
	ItemCount    int    `json:"item_count,omitempty"`
}

func main() {
	// Load .env file if it exists (for local development)
	_ = godotenv.Load()

	cfg := loadConfig()
	// Create HTTP client with custom transport that respects NO_PROXY
	transport := &http.Transport{
		Proxy: http.ProxyFromEnvironment,
	}
	client := &http.Client{
		Timeout:   cfg.HTTPTimeout,
		Transport: transport,
	}

	// Start as daemon: run continuously with a default check interval
	// Use environment variable to control the interval (in seconds), default to 3600 (1 hour)
	checkIntervalSec := intFromEnv("WORKER_CHECK_INTERVAL_SECONDS", 3600)
	if checkIntervalSec < 60 {
		checkIntervalSec = 60 // Minimum 1 minute
	}
	checkInterval := time.Duration(checkIntervalSec) * time.Second

	log.Printf("RSS Worker started. Check interval: %v", checkInterval)
	log.Printf("Django URL: %s", cfg.DjangoBaseURL)

	// Run continuously
	for {
		runWorkerIteration(client, cfg)
		log.Printf("Next check in %v seconds", checkIntervalSec)
		time.Sleep(checkInterval)
	}
}

func runWorkerIteration(client *http.Client, cfg workerConfig) {
	feeds, err := fetchFeeds(client, cfg)
	if err != nil {
		log.Printf("ERROR: failed to fetch feeds: %v", err)
		return
	}

	if len(feeds) == 0 {
		log.Println("INFO: no feeds configured")
		return
	}

	log.Printf("INFO: fetching %d feeds", len(feeds))
	results := fetchAllRSS(client, feeds, cfg.MaxConcurrency)
	reportFeedFetchResults(client, cfg, results)
	batchArticles := collectBatchArticles(results)

	if len(batchArticles) == 0 {
		log.Println("INFO: no new articles to ingest from this run")
		return
	}

	if err := postIngestWithRetry(client, cfg, batchArticles); err != nil {
		log.Printf("ERROR: ingest failed: %v", err)
		return
	}

	log.Printf("SUCCESS: sent %d deduplicated articles", len(batchArticles))
}

func loadConfig() workerConfig {
	baseURL := strings.TrimSpace(os.Getenv("DJANGO_BASE_URL"))
	if baseURL == "" {
		baseURL = defaultDjangoBaseURL
	}

	httpTimeoutSec := intFromEnv("HTTP_TIMEOUT_SECONDS", defaultHTTPTimeoutSec)
	maxConcurrency := intFromEnv("MAX_CONCURRENCY", defaultMaxConcurrency)
	if maxConcurrency < 1 {
		maxConcurrency = 1
	}
	ingestMaxRetry := intFromEnv("INGEST_MAX_RETRY", defaultIngestRetryCount)
	if ingestMaxRetry < 1 {
		ingestMaxRetry = 1
	}
	initialBackoffSec := intFromEnv("INGEST_INITIAL_BACKOFF_SECONDS", defaultInitialBackoffSec)
	if initialBackoffSec < 1 {
		initialBackoffSec = 1
	}

	apiToken := strings.TrimSpace(os.Getenv("WORKER_API_TOKEN"))

	return workerConfig{
		DjangoBaseURL:  strings.TrimRight(baseURL, "/"),
		HTTPTimeout:    time.Duration(httpTimeoutSec) * time.Second,
		MaxConcurrency: maxConcurrency,
		IngestMaxRetry: ingestMaxRetry,
		InitialBackoff: time.Duration(initialBackoffSec) * time.Second,
		APIToken:       apiToken,
	}
}

func intFromEnv(key string, defaultValue int) int {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return defaultValue
	}

	parsed, err := strconv.Atoi(raw)
	if err != nil {
		log.Printf("invalid %s=%q, using default=%d", key, raw, defaultValue)
		return defaultValue
	}

	return parsed
}

func fetchFeeds(client *http.Client, cfg workerConfig) ([]Feed, error) {
	url := cfg.DjangoBaseURL + feedsEndpoint
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, fmt.Errorf("build feed list request: %w", err)
	}
	if cfg.APIToken != "" {
		req.Header.Set("Authorization", "Token "+cfg.APIToken)
	}

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("feed list request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return nil, fmt.Errorf("feed list returned %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	var feeds []Feed
	if err := json.NewDecoder(resp.Body).Decode(&feeds); err != nil {
		return nil, fmt.Errorf("decode feed list: %w", err)
	}
	return feeds, nil
}

func fetchAllRSS(client *http.Client, feeds []Feed, maxConcurrency int) []feedFetchResult {
	results := make([]feedFetchResult, 0, len(feeds))
	ch := make(chan feedFetchResult, len(feeds))
	sem := make(chan struct{}, maxConcurrency)
	var wg sync.WaitGroup

	for _, feed := range feeds {
		feed := feed
		wg.Add(1)
		go func() {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			ch <- fetchSingleFeed(client, feed)
		}()
	}

	wg.Wait()
	close(ch)

	for result := range ch {
		results = append(results, result)
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].FeedName < results[j].FeedName
	})

	for _, result := range results {
		if result.Err != nil {
			log.Printf("feed fetch error [%s]: %v", result.FeedURL, result.Err)
			continue
		}
		if result.NotModified {
			log.Printf("feed not modified [%s]", result.FeedName)
			continue
		}
		log.Printf("feed fetched [%s]: %d items", result.FeedName, len(result.Articles))
	}

	return results
}

func fetchSingleFeed(client *http.Client, feed Feed) feedFetchResult {
	result := feedFetchResult{
		FeedID:    feed.ID,
		FeedName:  feed.Name,
		FeedURL:   feed.URL,
		FetchedAt: time.Now().UTC(),
	}

	req, err := http.NewRequest(http.MethodGet, feed.URL, nil)
	if err != nil {
		result.Err = fmt.Errorf("build request: %w", err)
		return result
	}
	req.Header.Set("Accept", "application/rss+xml, application/atom+xml, application/xml, text/xml")
	if strings.TrimSpace(feed.ETag) != "" {
		req.Header.Set("If-None-Match", feed.ETag)
	}
	if strings.TrimSpace(feed.LastModified) != "" {
		req.Header.Set("If-Modified-Since", feed.LastModified)
	}

	resp, err := client.Do(req)
	if err != nil {
		result.Err = fmt.Errorf("request failed: %w", err)
		return result
	}
	defer resp.Body.Close()

	result.HTTPCode = resp.StatusCode
	result.ETag = strings.TrimSpace(resp.Header.Get("ETag"))
	if result.ETag == "" {
		result.ETag = strings.TrimSpace(feed.ETag)
	}
	result.LastModified = strings.TrimSpace(resp.Header.Get("Last-Modified"))
	if result.LastModified == "" {
		result.LastModified = strings.TrimSpace(feed.LastModified)
	}
	if resp.StatusCode == http.StatusNotModified {
		result.NotModified = true
		return result
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		result.Err = fmt.Errorf("unexpected status %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
		return result
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		result.Err = fmt.Errorf("read body: %w", err)
		return result
	}

	articles, err := parseRSS(body, feed.ID)
	if err != nil {
		result.Err = fmt.Errorf("parse rss: %w", err)
		return result
	}

	result.Articles = articles
	result.ItemCount = len(articles)
	return result
}

func reportFeedFetchResults(client *http.Client, cfg workerConfig, results []feedFetchResult) {
	for _, result := range results {
		if result.FeedID == 0 {
			continue
		}
		if err := postFeedFetchStatus(client, cfg, result); err != nil {
			log.Printf("failed to report fetch status for %s: %v", result.FeedName, err)
		}
	}
}

func postFeedFetchStatus(client *http.Client, cfg workerConfig, result feedFetchResult) error {
	payload := feedStatusPayload{
		Status:       "success",
		HTTPStatus:   result.HTTPCode,
		ETag:         result.ETag,
		LastModified: result.LastModified,
		ItemCount:    result.ItemCount,
	}
	if result.NotModified {
		payload.Status = "not_modified"
	}
	if result.Err != nil {
		payload.Status = "error"
		payload.Error = result.Err.Error()
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal status payload: %w", err)
	}

	url := cfg.DjangoBaseURL + fmt.Sprintf(feedStatusEndpointFmt, result.FeedID)
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("build status request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if cfg.APIToken != "" {
		req.Header.Set("Authorization", "Token "+cfg.APIToken)
	}

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("status request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return fmt.Errorf("status endpoint returned %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}
	return nil
}

func parseRSS(xmlData []byte, feedID int) ([]IngestArticle, error) {
	var doc rssDocument
	if err := xml.Unmarshal(xmlData, &doc); err == nil && len(doc.Channel.Items) > 0 {
		return parseRSSItems(doc.Channel.Items, feedID), nil
	}

	var atom atomFeed
	if err := xml.Unmarshal(xmlData, &atom); err == nil && len(atom.Entries) > 0 {
		return parseAtomEntries(atom.Entries, feedID), nil
	}

	// Retry RSS unmarshal to get the error
	var doc2 rssDocument
	if err := xml.Unmarshal(xmlData, &doc2); err != nil {
		return nil, err
	}
	return parseRSSItems(doc2.Channel.Items, feedID), nil
}

func parseRSSItems(items []rssItem, feedID int) []IngestArticle {
	articles := make([]IngestArticle, 0, len(items))
	for _, item := range items {
		title := strings.TrimSpace(item.Title)
		link := strings.TrimSpace(item.Link)
		guid := strings.TrimSpace(item.GUID)

		if title == "" || link == "" {
			continue
		}

		article := IngestArticle{
			FeedID:   &feedID,
			Title:    title,
			Link:     link,
			GUID:     guid,
			Summary:  strings.TrimSpace(item.Description),
			Content:  strings.TrimSpace(item.Content),
			ImageURL: extractImageURL(item),
		}

		if parsedTime, ok := parsePubDate(item.PubDate); ok {
			formatted := parsedTime.UTC().Format(time.RFC3339)
			article.PublishedAt = &formatted
		}

		articles = append(articles, article)
	}
	return articles
}

func parseAtomEntries(entries []atomEntry, feedID int) []IngestArticle {
	articles := make([]IngestArticle, 0, len(entries))
	for _, entry := range entries {
		title := strings.TrimSpace(entry.Title)
		link := atomEntryLink(entry)
		if title == "" || link == "" {
			continue
		}

		summary := strings.TrimSpace(entry.Summary)
		content := strings.TrimSpace(entry.Content)

		article := IngestArticle{
			FeedID:  &feedID,
			Title:   title,
			Link:    link,
			GUID:    strings.TrimSpace(entry.ID),
			Summary: summary,
			Content: content,
		}

		pubDate := entry.Published
		if pubDate == "" {
			pubDate = entry.Updated
		}
		if parsedTime, ok := parsePubDate(pubDate); ok {
			formatted := parsedTime.UTC().Format(time.RFC3339)
			article.PublishedAt = &formatted
		}

		if content != "" {
			if m := imgSrcRe.FindStringSubmatch(content); len(m) > 1 {
				article.ImageURL = strings.TrimSpace(m[1])
			}
		}

		articles = append(articles, article)
	}
	return articles
}

func atomEntryLink(entry atomEntry) string {
	for _, l := range entry.Links {
		if l.Rel == "" || l.Rel == "alternate" {
			if u := strings.TrimSpace(l.Href); u != "" {
				return u
			}
		}
	}
	if len(entry.Links) > 0 {
		return strings.TrimSpace(entry.Links[0].Href)
	}
	return ""
}

func parsePubDate(value string) (time.Time, bool) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return time.Time{}, false
	}

	layouts := []string{
		time.RFC1123Z,
		time.RFC1123,
		time.RFC822Z,
		time.RFC822,
		time.RFC3339,
		time.RubyDate,
	}

	for _, layout := range layouts {
		parsed, err := time.Parse(layout, trimmed)
		if err == nil {
			return parsed, true
		}
	}

	return time.Time{}, false
}

func extractImageURL(item rssItem) string {
	// Priority 1: media:thumbnail
	if u := strings.TrimSpace(item.MediaThumbnail.URL); u != "" {
		return u
	}
	// Priority 2: media:content with medium="image" or image/* type
	for _, mc := range item.MediaContent {
		u := strings.TrimSpace(mc.URL)
		if u == "" {
			continue
		}
		if mc.Medium == "image" || strings.HasPrefix(mc.Type, "image/") {
			return u
		}
	}
	// Priority 3: enclosure with image/* type
	if u := strings.TrimSpace(item.Enclosure.URL); u != "" {
		if strings.HasPrefix(item.Enclosure.Type, "image/") {
			return u
		}
	}
	// Priority 4: first <img src="..."> in content or description
	for _, html := range []string{item.Content, item.Description} {
		if m := imgSrcRe.FindStringSubmatch(html); len(m) > 1 {
			return strings.TrimSpace(m[1])
		}
	}
	return ""
}

func collectBatchArticles(results []feedFetchResult) []IngestArticle {
	seen := make(map[string]struct{})
	batch := make([]IngestArticle, 0)

	for _, result := range results {
		if result.Err != nil {
			continue
		}

		for _, article := range result.Articles {
			key := dedupeKey(article)
			if _, exists := seen[key]; exists {
				continue
			}
			seen[key] = struct{}{}
			batch = append(batch, article)
		}
	}

	return batch
}

func dedupeKey(article IngestArticle) string {
	guid := strings.TrimSpace(article.GUID)
	if guid != "" {
		return "guid:" + guid
	}
	return "fallback:" + strings.TrimSpace(article.Title) + "|" + strings.TrimSpace(article.Link)
}

func postIngestWithRetry(client *http.Client, cfg workerConfig, articles []IngestArticle) error {
	var lastErr error
	backoff := cfg.InitialBackoff

	for attempt := 1; attempt <= cfg.IngestMaxRetry; attempt++ {
		lastErr = postIngest(client, cfg, articles)
		if lastErr == nil {
			return nil
		}

		if attempt == cfg.IngestMaxRetry {
			break
		}

		log.Printf("ingest attempt %d/%d failed: %v; retrying in %s", attempt, cfg.IngestMaxRetry, lastErr, backoff)
		time.Sleep(backoff)
		backoff *= 2
	}

	return fmt.Errorf("ingest failed after %d attempts: %w", cfg.IngestMaxRetry, lastErr)
}

func postIngest(client *http.Client, cfg workerConfig, articles []IngestArticle) error {
	payload, err := json.Marshal(articles)
	if err != nil {
		return fmt.Errorf("marshal ingest payload: %w", err)
	}

	url := cfg.DjangoBaseURL + ingestEndpoint
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("build ingest request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if cfg.APIToken != "" {
		req.Header.Set("Authorization", "Token "+cfg.APIToken)
	}

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("ingest request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return fmt.Errorf("ingest returned %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
	}

	var result ingestResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return fmt.Errorf("decode ingest response: %w", err)
	}

	log.Printf("ingest result: ok=%t received=%d created=%d skipped=%d", result.OK, result.Received, result.Created, result.Skipped)
	return nil
}
