
usage() {
cat <<_EOF_

tfce-cluster.sh prefix_tstatN voxel-p cluster-z

  voxel-p: threshold for prefix_tfce_corrp_tstatN
           typical value for tfce-corrected-p is 
           0.95 (i.e. p<0.05) or 0.99 (p<0.01)
           All corrected values are regarded as significant
           
  cluster-z: threshold for prefix_tstatN
             typical value for this are, (z[-logp])
             2.57[2] 3.29[3] 3.89[4] 4.41[5]  4.89[6]
             5.32[7] 5.73[8] 6.10[9] 6.47[10] 6.80[10]
             as significance is defined by voxel-p.
             Setting higher value is only for clustering purpose.
             That is to reduce the cluster size.
  
_EOF_
# r: qnorm(p/2, lower.tail=F)

}

export FSLOUTPUTTYPE=NIFTI_GZ
export FSLDIR=/Users/clive/fsl

mni=$FSLDIR/data/standard/MNI152_T1_2mm.nii.gz

input=$1

[ $(imtest $input) = 0 ] && usage && exit
input=$(remove_ext $input)
prefix=${input/_tfce_corrp_*/}
prefix=${prefix/_tstat*/}
tstat=${input/*tstat/tstat}
tstat=${tstat/*fstat/fstat}

corrp=${prefix}_tfce_corrp_${tstat}
tstat=${prefix}_${tstat}

echo "Prefix  : $prefix"
echo "- corrp: $corrp"
echo "- tstat: $tstat"

[ $(imtest $corrp) = 0 ] && echo "Invalid corrp: $corrp" && exit
[ $(imtest $tstat) = 0 ] && echo "Invalid tstat: $tstat" && exit

# Handle thresholds
[ "$2" = "" ] && corrpthr=0.95 || corrpthr=$2 
echo "- corrpthr: $corrpthr"

fslmaths $corrp -thr $corrpthr -bin ${corrp}_mask 
fslmaths ${corrp}_mask -mul $tstat ${tstat}_thresh
trange=$(fslstats ${tstat}_thresh -k ${corrp}_mask -R)
tmin=$(echo ${trange} | awk '{printf("%0.2f", $1)}')
tmax=$(echo ${trange} | awk '{printf("%0.2f", $2)}')
[ "$3" = "" ] && cluszthr=$tmin || cluszthr=$3 
echo "- cluszthr: $cluszthr (range: $tmin - $tmax)"

k=50
[[ "$4" =~ "^[0-9]+$" ]] && k=$4 && shift
echo "- k: $k"

[[ "$4" = "" ]] && outdir=${prefix}_p${corrpthr}_z${cluszthr} || outdir=${4}_p${corrpthr}_z${cluszthr} 
echo "outdir: $outdir"

mkdir -p $outdir
immv ${corrp}_mask ${outdir}
immv ${tstat}_thresh ${outdir}
cd $outdir

fsl-cluster -p 1 --in=${tstat}_thresh --thresh=$cluszthr --oindex=${tstat}_cluster_index --olmax=${tstat}_lmax.txt --osize=${tstat}_cluster_size --mm --minextent=$k | tee ${tstat}_cluster.txt

fslmaths  ${tstat}_thresh -mas ${tstat}_cluster_index ${tstat}_cluster

awk 'NR>1 {print $4, $5, $6}' ${tstat}_cluster.txt | std2imgcoord -img $mni -std $mni -vox - > ${tstat}_cluster_vox.txt

# Generate PNG files
c=( $(awk '{print $1}'  ${tstat}_cluster_vox.txt) )

if [ "$c" = "" ]; then
  echo "No result" >> ${tstat}.html
else
    x=( $(awk '{print $1}'  ${tstat}_cluster_vox.txt) )
    y=( $(awk '{print $2}'  ${tstat}_cluster_vox.txt) )
    z=( $(awk '{print $3}'  ${tstat}_cluster_vox.txt) )
    v=( $(awk 'NR>1 {print $2}'  ${tstat}_cluster.txt) )
    p=( $(awk 'NR>1 {print $3}'  ${tstat}_cluster.txt) )
    mx=( $(awk 'NR>1 {print $4}'  ${tstat}_cluster.txt) )
    my=( $(awk 'NR>1 {print $5}'  ${tstat}_cluster.txt) )
    mz=( $(awk 'NR>1 {print $6}'  ${tstat}_cluster.txt) )

    range=$( printf "%0.1f %0.1f" $(fslstats ${tstat}_cluster -l 0.0001 -R))
    overlay 1 0 $mni -a ${tstat}_cluster $range ${tstat}_rendered
    fslswapdim ${tstat}_rendered -x y z ${tstat}_flipx > /dev/null

    for (( i =  0; i < ${#z[@]}; i++ )) do
    n=$(( ${#z[@]} - i))
    fslmaths ${tstat}_cluster_index -thr $n -uthr $n -bin ${tstat}_cluster_${n}
    fslmaths ${tstat}_cluster -mas ${tstat}_cluster_${n} ${tstat}_cluster_${n}
    overlay 1 0 $mni -a ${tstat}_cluster_${n} $range ${tstat}_${n}_rendered
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
    echo "<table>" > ${tstat}.html
    echo "<tr><td>Cluster</td><td>Voxels</td><td>Max</td><td>X</td><td>Y</td><td>Z</td><td>AAL Label</td>" >> ${tstat}.html
    for (( i =  0; i < ${#z[@]}; i++ )) do
    n=$(( ${#z[@]} - i))
    l=$(   cat ${tstat}_cluster_${n}_aal.txt | grep -v "^NA\|^|\|^-\|^$" |awk -F '|' 'NR==1{next} $3 > max {max=$3; max_label=$1} END{print max_label}' )
    echo "<tr>"
    echo "  <td>$n</td>"
    echo "  <td>${v[$i]}</td>"
    echo "  <td>${p[$i]}</td>"
    echo "  <td>${mx[$i]}</td>"
    echo "  <td>${my[$i]}</td>"
    echo "  <td>${mz[$i]}</td>"
    echo "  <td>$l</td>"
    echo "</tr>"
    done >> ${tstat}.html
    echo "</table>" >> ${tstat}.html
    echo "<br><br>" >> ${tstat}.html

    #### Table with images at the peak voxel ####
    echo "<table>" >> ${tstat}.html
    echo "<tr><td>Cluster</td><td>Voxels</td><td>Max</td><td>X</td><td>Y</td><td>Z</td><td>Label</td></tr>" >> ${tstat}.html
    for (( i =  0; i < ${#z[@]}; i++ )) do
    echo "<tr>"
    n=$(( ${#z[@]} - i))
    echo "  <td>$n</td>"
    echo "  <td>${v[$i]}</td>"
    echo "  <td>${p[$i]}</td>"
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
    done >> ${tstat}.html
    echo "</table>" >> ${tstat}.html
fi

echo "see report: ${tstat}.html"
open ${tstat}.html

echo "Total time: $(printf "%02d:%02d:%02d" $((SECONDS/3600)) $((SECONDS/60%60)) $((SECONDS%60)) )"


exit

# remarks
tfce-cluster.sh highlow_tfce_corrp_tstat1.nii.gz .999 8
tfce-cluster.sh highlow_tfce_corrp_tstat1.nii.gz .999 8


# trash
awk 'NR>1 {print $4, $5, $6}' ${tstat}_cluster.txt > ${tstat}_cluster_mm.txt

cmd=""
while read x y z; do
  cmd="$cmd -c $x $y $z"
done <  ${tstat}_cluster_mm.txt
