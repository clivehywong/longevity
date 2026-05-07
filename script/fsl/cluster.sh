

usage() {
echo
[ "$@" != "" ] && echo "$@"

cat <<_EOF_

cluster.sh [ -p pthr ] [ -z zthr ] [ -t pos/neg/both ] [ -m mask ] [ -s smoothness ] [ -k size ] [ -d output dir ] [ -o output ] input
  -z: voxel threshold = 2.3 (voxel p < 0.05 if input is zstat)
  -p: cluster p cluster threshold = 0.05 (FWE p < 0.05)
  -s: smoothness = r (estimate with res4d file; alternative: z for zstat)
  -m: default: MNI152_2mm_brain_mask
  -k: minimum cluster size (default: 1)
  -d: output directory (default to input directory)
  -o: output prefix (default to image name)
_EOF_
exit
}

e() { echo $e; $e; }

input=stats/zstat1
outdir=""
out=""
voxt=2.3
fwep=0.05
k=1
outtype="p n"
mask=${FSLDIR}/data/standard/MNI152_T1_2mm_brain_mask_dil.nii.gz
m=mni
s=r
command="$0 $@"
mni=$FSLDIR/data/standard/MNI152_T1_2mm.nii.gz

while true; do
  case $1 in
    '') break; ;;
    -m) mask=$2; m=$(remove_ext $(basename $mask)); shift 2; ;;
    -z) voxt=$2; shift 2; ;; # voxel threshold
    -p) fwep=$2; shift 2; ;; # cluster p
    -t) outtype=$2; shift 2; ;;
    -s) ( [ "$2" = "r" ] || [ "$2" = "z" ] ) && s=$2 || usage "Invalid smoothness option, use [ -s r ] or [ -s z ]"
        shift 2; ;;
    -k) k=$2; shift 2; ;;
    -d) outdir=$2; shift 2; ;; 
    -o) out=$2; outdir=$(dirname $out); out=$(basename $out); shift 2; ;; 
    -seed) seed=$2; shift 2; ;; # not for analysis, but render on papaya
    *) input="$@"; break; ;;
  esac
done

# define variables
imgstat=$(readlink -f $input)
imgcope=${imgstat/zstat/cope}
statsdir=$(readlink -f $(dirname $input))

featdir=$(dirname $statsdir)
res4d=$statsdir/res4d
dof=$statsdir/dof
voxt=$(printf "%0.2f" $voxt)
fwep=$(printf "%0.3f" $fwep)
[ -z "$out" ] && out=$(remove_ext $(basename $input))
out=${out}_${m}_t${voxt}_p${fwep}_s${s}_k${k}
if [ -z "$outdir" ]; then
  outdir=$(readlink -f $(dirname $input))
else
  [ ${outdir:0:1} = "/" ] || outdir="$PWD/$outdir"
fi

# check required files
[ $(imtest $input) = 0 ] && usage "Input not found [ $input ]..."
[ "$s" = "r" ] && [ ! -f $statsdir/dof ] && usage "Missing stats/dof, try [ -s z ] to use zstat for smoothnest estimation."
[ "$s" = "r" ] && [ $(imtest $res4d) = 0 ] && usage "Invalid stats/res4d, try [ -s z ] to use zstat for smoothnest estimation."

echo ">>> img = $input \n>>> dir = $outdir \n>>> out = $out \n>>> p   = $fwep \n>>> t   = $voxt \n>>> msk = $(remove_ext $(basename $mask)) \n>>> smo = $s \n>>> dof = $dof \n>>> res = $res4d"

# Smoothness Estimate
if [ "$s" = "r" ]; then
  read dof < $dof
  cmd="smoothest -d $dof -m $mask -r $res4d"
else
  cmd="smoothest -z ${input} -m $mask "
fi

echo "Estimate smoothness: [ $cmd ]"
se=$( `echo $cmd` )
OFS=$IFS
IFS=$'\n'
for l in $se; do
  echo $l
  [ "${l/ *}" == "DLH" ] && DLH=${l/* }0
  [ "${l/ *}" == "RESELS" ] && RESELS=${l/* }0
  [ "${l/ *}" == "VOLUME" ] && VOLUME=${l/* }
done
IFS=$OFS

# Copy file
mkdir -p $outdir
imcp $imgstat $outdir/${out}
cd $outdir
fslmaths $out -mul 0 blank

for f in $outtype; do 
  if [ $f = "p" ]; then
    stattype="Activation"
    statpfx="act"
    tstat=${out}_${statpfx}
    echo fslmaths $out -thr $voxt ${tstat}_thresh
    fslmaths $out -thr $voxt ${tstat}_thresh
  else
    stattype="Deactivation"
    statpfx="dea"
    tstat=${out}_${statpfx}
    echo fslmaths $out -mul -1 -thr $voxt ${tstat}_thresh
    fslmaths $out -mul -1 -thr $voxt ${tstat}_thresh
  fi

  echo $stattype

  # Cluster
  echo
  echo "fsl-cluster -i ${tstat}_thresh -t $voxt --othresh=${tstat}_thresh -o ${tstat}_cluster_index --olmax=${tstat}_lmax.txt -p $fwep -r ${RESELS} -d ${DLH} --volume=${VOLUME} -c $imgcope --minextent=$k --mm | tee ${tstat}_cluster.txt"
  fsl-cluster -i ${tstat}_thresh -t $voxt --othresh=${tstat}_thresh -o ${tstat}_cluster_index --olmax=${tstat}_lmax.txt -p $fwep -d ${DLH} --volume=${VOLUME} -c $imgcope --minextent=$k --mm | tee ${tstat}_cluster.txt
  fslmaths  ${tstat}_thresh -mas ${tstat}_cluster_index ${tstat}_cluster

  awk 'NR>1 {print $6, $7, $8}' ${tstat}_cluster.txt | std2imgcoord -img $mni -std $mni -vox - > ${tstat}_cluster_vox.txt

  # Generate PNG files
  c=( $(awk '{print $1}'  ${tstat}_cluster_vox.txt) )

  if [ "$c" = "" ]; then
    echo "No result" 
  else
      x=( $(awk '{print $1}'  ${tstat}_cluster_vox.txt) )
      y=( $(awk '{print $2}'  ${tstat}_cluster_vox.txt) )
      z=( $(awk '{print $3}'  ${tstat}_cluster_vox.txt) )
      v=( $(awk 'NR>1 {print $2}'  ${tstat}_cluster.txt) )
      p=( $(awk 'NR>1 {print $3}'  ${tstat}_cluster.txt) )
      m=( $(awk 'NR>1 {print $5}'  ${tstat}_cluster.txt) )
      mx=( $(awk 'NR>1 {print $6}'  ${tstat}_cluster.txt) )
      my=( $(awk 'NR>1 {print $7}'  ${tstat}_cluster.txt) )
      mz=( $(awk 'NR>1 {print $8}'  ${tstat}_cluster.txt) )

      range=$( printf "%0.1f %0.1f" $(fslstats ${tstat}_cluster -l 0.0001 -R))
      if [ $f = "p" ]; then
        rangep=$range
        overlay 1 0 $mni -a ${tstat}_cluster $range ${tstat}_rendered
      else
        rangen=$range
        overlay 1 0 $mni -a blank 1 2 ${tstat}_cluster $range ${tstat}_rendered
      fi
      fslswapdim ${tstat}_rendered -x y z ${tstat}_flipx > /dev/null

      for (( i =  0; i < ${#z[@]}; i++ )) do
      n=$(( ${#z[@]} - i))
      fslmaths ${tstat}_cluster_index -thr $n -uthr $n -bin ${tstat}_cluster_${n}
      fslmaths ${tstat}_cluster -mas ${tstat}_cluster_${n} ${tstat}_cluster_${n}
      if [ $f = "p" ]; then
        overlay 1 0 $mni -a ${tstat}_cluster_${n} $range ${tstat}_${n}_rendered
      else
        overlay 1 0 $mni -a blank 1 2 ${tstat}_cluster_${n} $range ${tstat}_${n}_rendered
      fi
      fslswapdim ${tstat}_${n}_rendered -x y z ${tstat}_${n}_flipx > /dev/null
      done

      for (( i =  0; i < ${#z[@]}; i++ )) do
      n=$(( ${#z[@]} - i))
      slicer ${tstat}_${n}_rendered -s 3 -x -${x[$i]} ${tstat}_${n}_x${x[$i]}.png
      slicer ${tstat}_${n}_flipx -u -s 3 -y -${y[$i]} ${tstat}_${n}_y${y[$i]}.png
      slicer ${tstat}_${n}_flipx -u -s 3 -z -${z[$i]} ${tstat}_${n}_z${z[$i]}.png

      atlasq query aal3v1 -m ${tstat}_cluster_${n} > ${tstat}_cluster_${n}_aal.txt 
      atlasq query harvardoxford-cortical -l -m ${tstat}_cluster_${n} > ${tstat}_cluster_${n}_hoc.txt 
      atlasq query harvardoxford-subcortical -l -m ${tstat}_cluster_${n} > ${tstat}_cluster_${n}_hos.txt 
      atlasq query cerebellum_mnifnirt -l -m ${tstat}_cluster_${n} > ${tstat}_cluster_${n}_cbn.txt 
      done

      #### Simple Table ####
      for (( i =  0; i < ${#z[@]}; i++ )) do
      n=$(( ${#z[@]} - i))
      l=$(   cat ${tstat}_cluster_${n}_aal.txt | grep -v "^NA\|^|\|^-\|^$" |awk -F '|' 'NR==1{next} $3 > max {max=$3; max_label=$1} END{print max_label}' )
      echo "<tr>"
      echo "  <td>$n</td>"
      echo "  <td>${v[$i]}</td>"
      echo "  <td>${p[$i]}</td>"
      echo "  <td>${m[$i]}</td>"
      echo "  <td>${mx[$i]}</td>"
      echo "  <td>${my[$i]}</td>"
      echo "  <td>${mz[$i]}</td>"
      echo "  <td>$l</td>"
      echo "</tr>"
      done >> ${tstat}-simple.html

      #### Table with images at the peak voxel ####
      for (( i =  0; i < ${#z[@]}; i++ )) do
      echo "<tr>"
      n=$(( ${#z[@]} - i))
      echo "  <td>$n</td>"
      echo "  <td>${v[$i]}</td>"
      echo "  <td>${p[$i]}</td>"
      echo "  <td>${m[$i]}</td>"
      echo "  <td><img src=${tstat}_${n}_x${x[$i]}.png><br>x=${mx[$i]}</td>"
      echo "  <td><img src=${tstat}_${n}_y${y[$i]}.png><br>y=${my[$i]}</td>"
      echo "  <td><img src=${tstat}_${n}_z${z[$i]}.png><br>z=${mz[$i]}</td>"
      echo "  <td> <a href=\"https://neurosynth.org/locations/${mx[$i]}_${my[$i]}_${mz[$i]}_6/\"  target=\"_blank\" rel=\"noopener noreferrer\"> NeuroSynth </a><br>"
      echo "  <b>AALv3</b><br>"
      grep -v "^|\|^-\|^$" ${tstat}_cluster_${n}_aal.txt | grep -v "^|\|^-\|^$" | awk -F '|'  'NR>1 {printf("%s: %0.1f%%<br>", $1,$3)}'
      echo "  <b>HO-cort</b><br>"
      grep -v "^|\|^-\|^$" ${tstat}_cluster_${n}_hoc.txt | grep -v "^|\|^-\|^$" | awk -F '|'  'NR>1 {printf("%s: %0.1f%%<br>", $1,$3)}'
      echo "  <b>HO-subcort</b><br>"
      grep -v "^|\|^-\|^$" ${tstat}_cluster_${n}_hos.txt | grep -v "^|\|^-\|^$" | awk -F '|'  'NR>1 {printf("%s: %0.1f%%<br>", $1,$3)}'
      echo "  <b>Cerebellum</b><br>"
      grep -v "^|\|^-\|^$" ${tstat}_cluster_${n}_cbn.txt | grep -v "^|\|^-\|^$" | awk -F '|'  'NR>1 {printf("%s: %0.1f%%<br>", $1,$3)}'
      echo "</tr>"
      done >> ${tstat}-full.html
  fi
done

papaya.sh -p ${out}_act_cluster.nii.gz -n ${out}_dea_cluster.nii.gz -s "$seed" -o ${out}_papaya.html
echo "<html>
<head>
<style>
table, th, td {
  border: 1px solid black;
  border-collapse: collapse;
}
</style>
</head>
<body>
<iframe src=\"${out}_papaya.html\" width=\"100%\" height=\"800px\" frameborder=\"0\"></iframe>
<br>
<table>
<tr><td>Cluster</td><td>Voxels</td><td>p</td><td>Max</td><td>X</td><td>Y</td><td>Z</td><td>AAL Label</td>" > ${out}.html
for f in $outtype; do 
  if [ $f = "p" ]; then
    stattype="Activation"
    statpfx="act"
    tstat=${out}_${statpfx}
  else
    stattype="Deactivation"
    statpfx="dea"
    tstat=${out}_${statpfx}
  fi
  echo "<tr><td>$stattype</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td>"
  [ -f  ${tstat}-simple.html ] && cat ${tstat}-simple.html && rm ${tstat}-simple.html
done >> ${out}.html
echo "</table>" >> ${out}.html
echo "<br><br>" >> ${out}.html

echo "<table>" >> ${out}.html
echo "<tr><td>Cluster</td><td>Voxels</td><td>p</td><td>Max</td><td>X</td><td>Y</td><td>Z</td><td>Label</td></tr>" >> ${out}.html
for f in $outtype; do 
  if [ $f = "p" ]; then
    stattype="Activation"
    statpfx="act"
    tstat=${out}_${statpfx}
  else
    stattype="Deactivation"
    statpfx="dea"
    tstat=${out}_${statpfx}
  fi
  echo "<tr><td>$stattype</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>" 
  [ -f  ${tstat}-full.html ] && cat ${tstat}-full.html && rm ${tstat}-full.html 
done >> ${out}.html
echo "</table>" >> ${out}.html
echo "</body>" >> ${out}.html
echo "</html>" >> ${out}.html


statpfx="act"
tstat=${out}_${statpfx}
fslmaths ${out}_act_cluster -sub ${out}_dea_cluster ${out}_thresh

# open ${out}.html

echo "see report: $outdir/${out}.html"
echo "see papaya: $outdir/${out}_papaya.html"

echo "Total time: $(printf "%02d:%02d:%02d" $((SECONDS/3600)) $((SECONDS/60%60)) $((SECONDS%60)) )"
exit



# Remarks
genCortMask () {
  fslmaths ${FSLDIR}/data/atlases/HarvardOxford/HarvardOxford-sub-maxprob-thr25-2mm.nii.gz -thr 9 -bin c1
  fslmaths ${FSLDIR}/data/atlases/HarvardOxford/HarvardOxford-sub-maxprob-thr25-2mm.nii.gz -uthr 7 -bin c2
  fslmaths $c1 -add $c2 -bin HOC
}
