#!/usr/bin/env bash

LC_ALL=C
LANG=C
export LC_ALL LANG

seed_dir="/volume2/@transmission"
watch_dir="/volume1/video/Torrents"
log_file="$(cd "${BASH_SOURCE[0]%/*}" && pwd)/log.log"

tr_binary() {
	"/var/packages/transmission/target/bin/transmission-remote" "$@"
}

av_regex='[^[:alnum:]]((n|k|kb)[0-3][0-9]{3}|1000[[:space:]_-]?giri|10mu(sume)?|1pon(do)?|[ch]0930|carib(bean|pr|com)*|fc2(ppv)?|g[[:space:]_-]?queen|girls[[:space:]_-]?delta|h4610|heydouga[0-9]{,4}|heyzo|honnamatv|jukujo[[:space:]_-]?club|kin8tengoku|mesubuta|mura(mura)?|nyoshin|paco(pacomama)?|th101|tokyo[[:space:]_-]?hot|xxx[[:space:]_-]?av|((259)?luxu|abpn?|abs|acme|adn|adz|aed|agav|agmx|akb|akbd|akdl|akid|ald|ama|ambi|ambs|anb|anci|anx|anzd|apaa|apkh|apns?|apod|apsh|aqmb|aqsh|aquarium|ara|arkx|arm|arso|asi|atad|atgo|athb|atid|atkd|atom|aukg|auks|av9898|avsa|axbc|bacn|baem|bahp|bazx|bbacos|bban|bbi|bbss|bcdp|bcpv|bda|bdd|bdsr|bf|bgn|bgsd|bid|bijn|bkd|blk|blkw|blor|bmst|bmw|bndv|bngd|bnjc|bokd|bouga|bstc|bur|cadv|cawd|cead|cesd|cetd|cho|chrv|cjob|cjod|clot|club|cmc|cmi|cmn|cmv|cnd|con|core|cmd|cosq|coterieav|cpde|crd|crs|crynm|csct|cvdx|cw3d2d(bd)?|cwdv|cwhdbd|cwp(bd)?|cz(bd)?|dac|dandy|daru|dasd|davk|dbam|dbe|dber|dbud|dcv|dcx|ddhh|ddhz|ddkm|ddob|dems|der|dfe|dic|dipo|djam|djsk|dksb|dlis|dmat|dmg|dmow|dnjr|dnw|docp|doj|doki|doks|dpmi|dpmx|drc(bd)?|drg(bd)?|dsam(bd)?|dss|dtsg|dtt|dv(aj)?|dvdms|dvh|eb(od)?|ecb|ecr|ekdv|ekw|eldx|embz|emh|emot|emp|emrd|endx|erika|esk|etqr|evis|evo|ewdx|eyan|eys|fadss|fcdc|fch|fffs|fgan|fh|fiv|flav|fneo|fone|fsdss|fset|fst|fuga|gachi[a-z]*|gana|gar|gaso?|gate|gavhj|gbsa|gdga|gdhh|gedo|geki|genm?|gens|gent|gerk|gexp|ggen|ggfh|ggtb|gigl|gma|gmem|gmmd|gnab|gnax|godr|gods?|goju|gomk|gptm|grch|gret|gryd|gs(ad)?|gtj|gun|gvg|gvh|gvsa|gxxd|gyan|gyd|gzap|havd|hawa|hbad|hdka|hey|hez|hgot|hhkl|hikr|hisn|hitma|hjmo|hkd|hmdn|hmgl|hnd|hndb|hnds|hnm|hodv|hoks|homa|honb|hone|hrv|hsam|hthd|hunta?|hunvr|husr|hyk|hypn|hzgd|ianf|ibw|idbd|idol|ids|iene|ienf|iesp|ikep|inct|inu|ipsd|iptd|ipx|ipz|iqqq|itsr|iwan|jac|jav|jbd|jbjb|jiro|jjaa|jjbk|jjda|jksr|jmty|josi|jotk|jpgc|jrw|jrzd|juc|jufd|jufe|jukd|jukf|jul|juny|jup|jura|jux|juy|ka(gp)?|kag|kapd|katu|kav|kawd|kbi|kbkd|kcda|keed|kfne|kg|kibd|kimu|kir|kird|kisd|kjn|kkj|kmhrs|knam|knb|knmd|kosatsu|kp|krhk|kri|kru|krvs|ks(bj)?|ksko|ktb|ktds|ktkc|ktkl|ktkz|ktra|kud|kuf|lady|laf(bd)?|ld|lhtd|licn|lmpi|lol|loli|loo|luke|lulu|lzdq|lzpl|maan|macb|mada|madm|man|mane|mas|mbm|mbrba|mcb3d(bd)?|mcbd|mcsr|mct|mdb|mdbk|mded|mds|mdtm|mdyd|meko|mers|meyd|mg(jh)?|mgdn|mgmq|mgt|miaa|miad|miae|mias|mibd|midd|mide|mifd|migd|miha|miid|mild|milk|mimk|mint|mird|mism|mist|mium|mizd|mk3d2d(bd)?|mkbd[[:space:]_-]?s|mkd[[:space:]_-]?s|mkmp|mkon|mlsm|mmb|mmgh|mmkz|mmnd|mmo|mmus|mmym|mntj|moed|moko|mond|mone|mopg|mubd|mrm|mrss|msbd|msfh|mtm|mtn|mucd|much|mud|mudr|mukd|mvsd|mw|mx(bd)?|mxgs?|mxsps|mxx|myab|myba|mywife|nacr|nacx|nash|natr|ncyf|ndra|ndwq|nem|neo|ngks|ngod|nhdtb|nikm|nine|nip|nitr|nkk?d|nnpj|nps|nslg|nsm|nsps|nss|nsstl|ntk|ntsu|nttr|nubi|nukimax|nxg|nzk|oae|oba|odv|odvhj|ofcd|ofje|ofku|oigs|okax|okb|okk|okp|oksn?|okx|okyh|omt|oned|onez|ons|onsd|onsg|opc|opd|open|opkt|oppw|opud|orebms|orec|otim|ovg|oyc|pako|panza|papa|parathd|pbd?|pcas|pgd|pih?|piyo|pjd|pkpd|pla|pokp|pokq|post|ppbd?|pppd?|ppsd|ppt|pred|psst|ptks|ptnoz|pts?|pym|r?nhdta?|ray|rbd?|rbs|rctd?|rcts|rd|real|rebd|red|reid|rfks|rhj|rix|rjmd|rki|rmdbb|rmds|rmld|room|rpin|rse|ruko|rvg|s-?cute|s2m(bd)?|s2mcr|s3dbd|saba|sace|sad|salo|sama|scd|scg|scop|scp|scpx|scr|sdab|sdam|sdcm|sdde|sddm|sdfk|sdjs|sdmf|sdmm|sdmt|sdmu|sdnm|sdnt|sdtop|semc|send|senn|sero|sga?|sgsr|shiroutozanmai|shisaku|shkd|shm|shn|shyn|silk|sim|simm|siro|sis|sivr|skmj|sksk|sky(hd)?|sky237|sm3d2d(bd)?|smb?d|smdv|smr|snis|snkh|sntj|soan|soav|soe|soju|sora|sprd|sps?|spye|spz|sqis|sqte|srcn|srmc|srs?|srxv|ss(kj)?|ssni|sspd|stars?|stfx|stko|stp|suke|supa|supd|svdvd|svnd|svoks|sw|sy(bi)?|sykh|tbb|tbl|tbw|tcd|tcm|tdln|tdp?|tek|tggp|thnd|thp|thz|tikb|tikc|tikf|tikp|tkbn|tki|tmd|tms|toen|tomn|tor|totugeki|tre|trg|trp|tsdl|tsgs|tsnd|tsp|tswn?|ttre|tue|tus|tushy|tyod|tzz|uljm|umd|umso|upsm|ure|urfd|urkk|urlh|urpw|usag|usba|vagu|vdd|vec|vema|venu|veq|vgd|vnds|voss|vov|vrtm|vspdr|vspds|wanz|wdi|wei|wfr|wkd|wpc|wzen|x1x|xmom|xrw|xv(sr)?|yako|yap|ylwn|ymdd|ymsr|yrh|yrz|ysad|ysn|yst|ytr|yuu|yzd|zeaa|zex|zmar|zmen|zuko|zzr)[[:space:]_-]?[0-9]{2,6})[^[:alnum:]]|[a-z]{2,}0[0-9]{4,}hhb|creampie'

if [[ ! -s $log_file ]]; then
	printf '%-20s %-10s %-35s %s\n' "Date" "Status" "Destination" "Name" >"$log_file"
fi

write_log() {
	printf -v text '%-20(%D %T)T %-10s %-35s %s' '-1' "$1" "${2:0:32}" "$3"
	sed -i "1a ${text}" "$log_file"
}

if [[ -n ${TR_TORRENT_DIR} && -n ${TR_TORRENT_NAME} ]]; then
	if [[ ! -e "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" ]]; then
		write_log "Missing" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
		exit
	fi

	if [[ ${TR_TORRENT_DIR} == "${seed_dir}" ]]; then

		[[ -z ${file_list:="$(find "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" -not -name "[@#.]*" -size +50M)"} ]] &&
			file_list="$(find "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" -not -name "[@#.]*")"
		file_list="$(cut -c "$((${#TR_TORRENT_DIR} + 1))-" <<<"${file_list,,}")"

		if grep -Eqf <(printf '%s\n' "${av_regex}") <<<"${file_list}"; then
			DESTINATION="/volume1/driver/Temp"

		elif grep -Eq '[^[:alnum:]]([se][0-9]{1,2}|s[0-9]{1,2}e[0-9]{1,2}|ep[[:space:]_-]?[0-9]{1,3})[^[:alnum:]]' <<<"${file_list}"; then
			DESTINATION="/volume1/video/TV Series"

		elif [[ ${TR_TORRENT_NAME,,} =~ (^|[^[:alnum:]])(acrobat|adobe|animate|audition|dreamweaver|illustrator|incopy|indesign|lightroom|photoshop|prelude|premiere)([^[:alnum:]]|$) ]]; then
			DESTINATION="/volume1/homes/admin/Download/Adobe"

		elif [[ ${TR_TORRENT_NAME,,} =~ (^|[^[:alnum:]])(windows|mac(os)?|x(86|64)|(32|64)bit|v[0-9]+\.[0-9]+)([^[:alnum:]]|$)|\.(zip|rar|exe|7z|dmg|pkg)$ ]]; then
			DESTINATION="/volume1/homes/admin/Download"

		else
			DESTINATION="/volume1/video/Films"
		fi

		[[ -d "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" ]] || DESTINATION="${DESTINATION}/${TR_TORRENT_NAME%.*}"
		[[ -d ${DESTINATION} ]] || mkdir -p "${DESTINATION}"

		if cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${DESTINATION}/"; then
			write_log "Finish" "${DESTINATION}" "${TR_TORRENT_NAME}"
		else
			write_log "Error" "${DESTINATION}" "${TR_TORRENT_NAME}"
		fi

	else

		if cp -rf "${TR_TORRENT_DIR}/${TR_TORRENT_NAME}" "${seed_dir}/"; then
			write_log "Finish" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
			tr_binary -t "$TR_TORRENT_ID" --find "${seed_dir}/"
		else
			write_log "Error" "${TR_TORRENT_DIR}" "${TR_TORRENT_NAME}"
		fi

	fi
fi

exec {lock_fd}<"${BASH_SOURCE[0]}" && flock -n "${lock_fd}" || exit

tr_info="$(tr_binary -t all -i)" && [[ -n ${tr_info} ]] || exit 1

grep -zvxFf <(sed -En 's/^[[:space:]]+Name: (.+)/\1/p' <<<"$tr_info") <(find "${seed_dir}" -mindepth 1 -maxdepth 1 -not -name "[.@#]*" -printf "%P\0") |
	while IFS= read -r -d '' name; do
		[[ -z $name ]] && continue
		write_log "Cleanup" "${seed_dir}" "${name}"
		rm -rf "${seed_dir:?}/${name}"
	done

space_threshold=$((80 * 1024 * 1024))
short_of_space() {
	space="$(df /volume2 --output=avail | sed -n '2p')"
	if [[ -n $space && $space -lt $space_threshold ]]; then
		return 0
	else
		return 1
	fi
}

if short_of_space; then
	while IFS= read -r -d '' line; do
		[[ -z $line ]] && continue
		write_log "Remove" "${seed_dir}" "${line#*/}"
		tr_binary -t "${line%%/*}" --remove-and-delete
		short_of_space || break
	done < <(
		awk -F": " '
			BEGIN {
				seed_threshold = ( systime() - 86400 )
				split("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec",months," ")
				for(i=1;i<=12;i++) mon[months[i]] = i
			}
			/^[[:space:]]+Id:[[:space:]]/ {id=$2;name="";percent="";next}
			id && !name && /^[[:space:]]+Name:[[:space:]]/ {name=$0;sub(/^[[:space:]]+Name:[[:space:]]/, "", name);next}
			id && !percent && /^[[:space:]]+Percent Done:[[:space:]]/ {if ($2 ~ /100%/) percent=$2; else id="";next}
			id && name && percent && /^[[:space:]]+Latest activity:[[:space:]]/ {
				sub(/^[[:space:]]+/, "", $2)
				if ($2)
				{
					split($2,date," ")
					m = date[2]; d = date[3]; t = date[4]; y = date[5]; gsub(":"," ",t)
					last_activate = mktime(y " " mon[m] " " d " " t)
					if ( last_activate && last_activate < seed_threshold ) array[last_activate"."NR] = (id "/" name)
				}
				id="";next
			}
			END {
				PROCINFO["sorted_in"] = "@ind_num_asc"
				for (i in array) printf "%s\0", array[i]
			}' <<<"$tr_info"
	)
fi

find "$watch_dir" -type f -empty -delete
tr_binary -t all -s
