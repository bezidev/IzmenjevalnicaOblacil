for filename in *.png; do
  filename=$(basename -- "$filename")
  extension="${filename##*.}"
  filename="${filename%.*}"
  echo "$filename"
  convert "$filename.png" "$filename-original.webp"
  convert "$filename.png" -quality 80 -resize 1100x1100 "$filename.webp"
  convert "$filename.png" -quality 80 -resize 500x500 "$filename-small.webp"
done