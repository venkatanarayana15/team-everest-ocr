void update_ocr(Volunteer_Home_Visited_Form rec)
{
	if(rec.OCR_Status == "Yes")
	{
		info "OCR already completed for record ID: " + rec.Applicant_ID;
	}
	else
	{
		try 
		{
			if(rec.Upload_Home_Visit_Form == null || rec.Upload_Home_Visit_Form.size() == 0)
			{
				info "No file found for record ID: " + rec.Applicant_ID;
			}
			else
			{
				clientId = thisapp.variables.update_ocr.ZOHO_CLIENT_ID;
				clientSecret = thisapp.variables.update_ocr.ZOHO_CLIENT_SECRET;
				refreshToken = thisapp.variables.update_ocr.ZOHO_REFRESH_TOKEN;
				tokenResponse = invokeurl
				[
					url :"https://accounts.zoho.com/oauth/v2/token"
					type :POST
					parameters:{"refresh_token":refreshToken,"client_id":clientId,"client_secret":clientSecret,"grant_type":"refresh_token"}
				];
				accessToken = tokenResponse.get("access_token");
				if(accessToken == null || accessToken == "")
				{
					info "Failed to generate access token: " + tokenResponse;
				}
				else
				{
					projectUrl = "https://biwwbmxgeumzhyjbxbip.supabase.co";
					bucketName = "files";
					supabaseKey = thisapp.variables.update_ocr.SUPABASE_SERVICE_ROLE_KEY;

					ownerName = "teameverest";
					appLinkName = "iatc-selection-one-app";
					reportLinkName = "Volunteer_Home_Visited_Form_Report";
					fileFieldLinkName = "Upload_Home_Visit_Form";
					
					// 🛠️ CRITICAL FIX: Removed the empty () method to stop Zoho from falling back to the internal 18-digit ID
					applicantId = rec.Applicant_ID_String;
					// Example: rec.Applicant_ID.Application_Number or rec.Applicant_ID.Form_Status_Field

					allowedExtensions = List();
					allowedExtensions.add("pdf");
					allowedExtensions.add("jpg");
					allowedExtensions.add("jpeg");
					allowedExtensions.add("png");
					allowedExtensions.add("webp");

					fileList = rec.Upload_Home_Visit_Form;
					uploadedPaths = List();
					fileIndex = 0;
					allUploadsOk = true;

					for each originalFileName in fileList
					{
						if(originalFileName == null || originalFileName == "")
						{
							continue;
						}

						fileParts = originalFileName.toList(".");
						extension = "";

						if(fileParts.size() > 1)
						{
							extension = fileParts.get(fileParts.size() - 1).toLowerCase();
						}

						if(!allowedExtensions.contains(extension))
						{
							info "Unsupported file type for record ID: " + applicantId + ". File: " + originalFileName;
							continue;
						}

						// 🛠️ FIX: Keep PDFs as standalone names, add sequential suffixes ONLY to images
						if(extension == "pdf")
						{
							newFileName = applicantId + ".pdf";
						}
						else
						{
							displayIndex = fileIndex + 1;
							newFileName = applicantId + "_" + displayIndex + "." + extension;
						}

						// folder per applicant: files/{applicantId}/{applicantId}.ext
						folderPath = applicantId + "/" + newFileName;

						// 🛠️ FIXED: Used the proper zoho.encryption wrapper function for URL encoding
						encodedFilePath = zoho.encryption.urlEncode(originalFileName);
						downloadUrl = "https://www.zohoapis.com/creator/v2.1/data/" + ownerName + "/" + appLinkName + "/report/" + reportLinkName + "/" + rec.ID + "/" + fileFieldLinkName + "/download?filepath=" + encodedFilePath;

						actualFileObj = invokeurl
						[
							url :downloadUrl
							type :GET
							headers:{"Authorization":"Zoho-oauthtoken " + accessToken}
						];

						if(actualFileObj == null)
						{
							info "Failed to download file '" + originalFileName + "' for record ID: " + applicantId;
							allUploadsOk = false;
						}
						else
						{
							actualFileObj.setFileName(newFileName);

							contentType = "application/octet-stream";
							if(extension == "pdf")
							{
								contentType = "application/pdf";
							}
							else if(extension == "jpg" || extension == "jpeg")
							{
								contentType = "image/jpeg";
							}
							else if(extension == "png")
							{
								contentType = "image/png";
							}
							else if(extension == "webp")
							{
								contentType = "image/webp";
							}

							uploadUrl = projectUrl + "/storage/v1/object/" + bucketName + "/" + folderPath;

							uploadResponse = invokeurl
							[
								url :uploadUrl
								type :PUT
								parameters:actualFileObj
								headers:{"Authorization":"Bearer " + supabaseKey,"apikey":supabaseKey,"x-upsert":"true","Content-Type":contentType}
							];

							info "Supabase upload response for " + folderPath + ": " + uploadResponse;

							if(uploadResponse != null && uploadResponse.toString().toLowerCase().contains("error"))
							{
								info "Supabase upload failed for " + folderPath + " -> " + uploadResponse;
								allUploadsOk = false;
							}
							else
							{
								uploadedPaths.add(bucketName + "/" + folderPath);
							}
						}

						fileIndex = fileIndex + 1;
					}

					if(uploadedPaths.size() == 0)
					{
						info "No files were successfully uploaded for record ID: " + applicantId;
					}
					else
					{
						// backend processes the whole applicant folder
						applicantFolderPath = bucketName + "/" + applicantId;

						backendResponse = invokeurl
						[
							url :"https://YOUR_BACKEND_DOMAIN/api/ocr/extract"
							type :POST
							parameters:{"record_id":applicantId,"folder_path":applicantFolderPath,"file_paths":uploadedPaths,"bucket":bucketName}
							headers:{"Content-Type":"application/json"}
								];

						info "Backend OCR response: " + backendResponse;

						if(backendResponse != null && backendResponse.get("success") == true)
						{
							update Volunteer_Home_Visited_Form[Applicant_ID == rec.Applicant_ID]
							[
								OCR_Status="Yes"
							];
							info "OCR completed and status updated for record ID: " + applicantId;
						}
						else
						{
							info "Backend OCR extraction failed for record ID: " + applicantId + " -> " + backendResponse;
						}
					}
				}
			}
		}
		catch (e)
		{
			info "Exception in update_ocr for record ID " + rec.Applicant_ID + ": " + e;
		}
	}
}





void update_ocr(Volunteer_Home_Visited_Form rec)
{
	if(rec.OCR_Status == "Yes")
	{
		return;
	}
	payload = Map();
	payload.put("record_id",rec.Applicant_ID_String);
	payload.put("zoho_app_owner","teameverest");
	payload.put("zoho_app_link_name","iatc-selection-one-app");
	payload.put("zoho_report_link_name","Volunteer_Home_Visited_Form_Report");
	payload.put("zoho_record_id",rec.ID.toString());
	payload.put("file_field_link_name","Upload_Home_Visit_Form");
	payload.put("file_names",rec.Upload_Home_Visit_Form);
	payload.put("bucket","files");
	response = invokeurl
	[
		url :"https://tapping-illicitly-capture.ngrok-free.dev/api/ocr/extract"
		type :POST
		body:payload.toString()
		headers:{"Content-Type":"application/json"}
	];
	info response;
}

