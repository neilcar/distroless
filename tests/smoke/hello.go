// Static test binary for the `static` image: proves CA certificates and tzdata work.
package main

import (
	"fmt"
	"net/http"
	"os"
	"time"
)

func main() {
	if _, err := time.LoadLocation("America/New_York"); err != nil {
		fmt.Println("tzdata:", err)
		os.Exit(1)
	}
	resp, err := (&http.Client{Timeout: 15 * time.Second}).Get("https://ghcr.io/v2/")
	if err != nil {
		fmt.Println("tls:", err)
		os.Exit(1)
	}
	resp.Body.Close()
	fmt.Println("ok")
}
